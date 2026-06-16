from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .contracts import ScannerCandidate


@dataclass
class ManagedCandidate:
    symbol: str
    candidate_score: float
    discovery_rank: Optional[int]
    recommendation_hint: str
    exchange: Optional[str]
    screener: Optional[str]
    tags: List[str]
    reasons: List[str]
    metadata: Dict[str, Any]


def _get_attr(candidate: Any, key: str, default: Any = None) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(key, default)
    return getattr(candidate, key, default)


def _metadata(candidate: Any) -> Dict[str, Any]:
    metadata = _get_attr(candidate, "metadata", {}) or {}
    if hasattr(metadata, "model_dump"):
        return metadata.model_dump()
    return dict(metadata)


def normalize_scanner_candidate(candidate: Any) -> ManagedCandidate:
    metadata = _metadata(candidate)
    symbol = _get_attr(candidate, "symbol", metadata.get("symbol", ""))
    score = _get_attr(candidate, "candidate_score", None)
    if score is None:
        score = _get_attr(candidate, "confidence_score", None)
    if score is None:
        score = metadata.get("candidate_score") or metadata.get("final_score") or 0.0
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0

    recommendation_hint = _get_attr(candidate, "recommendation_hint", None)
    if recommendation_hint is None:
        recommendation_hint = _get_attr(candidate, "recommendation", None)
    if recommendation_hint is None:
        recommendation_hint = metadata.get("recommendation_hint", "WATCHLIST")

    return ManagedCandidate(
        symbol=str(symbol).upper().strip(),
        candidate_score=max(0.0, min(1.0, score)),
        discovery_rank=metadata.get("discovery_rank"),
        recommendation_hint=str(recommendation_hint or "WATCHLIST"),
        exchange=metadata.get("exchange") or _get_attr(candidate, "exchange", None),
        screener=metadata.get("screener") or _get_attr(candidate, "screener", None),
        tags=list(metadata.get("tags") or _get_attr(candidate, "tags", []) or []),
        reasons=list(metadata.get("reasons") or _get_attr(candidate, "reasons", []) or []),
        metadata=metadata,
    )


def select_candidates_for_analysis(candidates: Iterable[Any], max_candidates: int = 10) -> List[str]:
    normalized = [normalize_scanner_candidate(candidate) for candidate in candidates]
    normalized = [candidate for candidate in normalized if candidate.symbol]
    normalized.sort(key=lambda item: (item.candidate_score, -(item.discovery_rank or 999999)), reverse=True)
    return [candidate.symbol for candidate in normalized[:max_candidates]]


def build_candidate_context(candidates: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    context: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        item = normalize_scanner_candidate(candidate)
        if not item.symbol:
            continue
        context[item.symbol] = {
            "candidate_score": item.candidate_score,
            "discovery_rank": item.discovery_rank,
            "recommendation_hint": item.recommendation_hint,
            "exchange": item.exchange,
            "screener": item.screener,
            "tags": item.tags,
            "reasons": item.reasons,
            "metadata": item.metadata,
        }
    return context
