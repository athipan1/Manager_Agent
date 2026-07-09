"""Pure scanner candidate normalization helpers for Manager_Agent."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .serialization_service import normalize_score

_CANDIDATE_FIELDS = [
    "symbol",
    "candidate_score",
    "confidence_score",
    "fundamental_score",
    "technical_score",
    "discovery_rank",
    "recommendation",
    "recommendation_hint",
    "exchange",
    "screener",
    "tags",
    "reasons",
    "raw_scores",
    "bucket_hint",
    "metadata",
]


def candidate_to_dict(candidate: Any) -> Dict[str, Any]:
    """Normalize a scanner candidate model/dict/object into a dictionary."""
    if isinstance(candidate, dict):
        return candidate
    if hasattr(candidate, "model_dump"):
        return candidate.model_dump(mode="json")
    return {
        key: getattr(candidate, key)
        for key in _CANDIDATE_FIELDS
        if hasattr(candidate, key)
    }


def scanner_candidate_symbol(candidate: Any) -> Optional[str]:
    """Return the candidate symbol, if present."""
    return candidate_to_dict(candidate).get("symbol")


def scanner_candidate_score(candidate: Any) -> float:
    """Return the best available normalized score for ranking candidates."""
    data = candidate_to_dict(candidate)
    metadata = data.get("metadata") or {}
    raw_scores = data.get("raw_scores") or metadata.get("raw_scores") or {}

    score_candidates = [
        data.get("candidate_score"),
        data.get("confidence_score"),
        data.get("fundamental_score"),
        raw_scores.get("fundamental_score")
        if isinstance(raw_scores, dict)
        else None,
        raw_scores.get("quality_score")
        if isinstance(raw_scores, dict)
        else None,
    ]

    for value in score_candidates:
        score = normalize_score(value)
        if score > 0:
            return score

    try:
        rank = int(
            data.get("discovery_rank")
            or metadata.get("discovery_rank")
        )
        return (
            max(0.1, min(1.0, 1.0 - ((rank - 1) * 0.08)))
            if rank > 0
            else 0.0
        )
    except (TypeError, ValueError):
        return 0.0


def scanner_candidate_metadata(candidate: Any) -> Dict[str, Any]:
    """Return normalized candidate metadata for reports/audit records."""
    data = candidate_to_dict(candidate)
    metadata = data.get("metadata") or {}
    return {
        "candidate_score": data.get("candidate_score"),
        "confidence_score": data.get("confidence_score"),
        "fundamental_score": data.get("fundamental_score"),
        "technical_score": data.get("technical_score"),
        "discovery_rank": (
            data.get("discovery_rank")
            or metadata.get("discovery_rank")
        ),
        "recommendation": data.get("recommendation"),
        "recommendation_hint": data.get("recommendation_hint"),
        "exchange": data.get("exchange") or metadata.get("exchange"),
        "screener": data.get("screener") or metadata.get("screener"),
        "tags": data.get("tags") or metadata.get("tags"),
        "reasons": data.get("reasons") or metadata.get("reasons"),
        "raw_scores": (
            data.get("raw_scores") or metadata.get("raw_scores")
        ),
        "bucket_hint": data.get("bucket_hint"),
        "metadata": metadata,
    }
