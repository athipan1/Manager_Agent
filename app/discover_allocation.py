from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

from .portfolio_allocation import (
    CORE_DIVIDEND,
    NEWS_MOMENTUM,
    UNASSIGNED,
    VALUE_REBOUND,
    build_strategy_allocation_plan,
    classify_strategy_bucket_decision,
)
from .strategy_bucket_classifier import (
    AUTO_CLASSIFY_THRESHOLD,
    CLASSIFIER_VERSION,
)


BUCKET_PRIORITY = (CORE_DIVIDEND, VALUE_REBOUND, NEWS_MOMENTUM)
DEFAULT_BUCKET_SELECTION_LIMITS = {
    CORE_DIVIDEND: 2,
    VALUE_REBOUND: 2,
    NEWS_MOMENTUM: 1,
}


def _score(item: Mapping[str, Any]) -> Decimal:
    try:
        return Decimal(
            str(
                (item.get("score_breakdown") or {}).get(
                    "final_opportunity_score"
                )
                or 0
            )
        )
    except Exception:
        return Decimal("0")


def _verdict(item: Mapping[str, Any]) -> str:
    analysis = item.get("analysis") or {}
    if hasattr(analysis, "model_dump"):
        analysis = analysis.model_dump(mode="json")
    if isinstance(analysis, Mapping):
        return str(analysis.get("final_verdict") or "hold").lower()
    return "hold"


def _classification(item: Mapping[str, Any]) -> Dict[str, Any]:
    existing = item.get("strategy_bucket_classification")
    if isinstance(existing, Mapping):
        return dict(existing)
    return classify_strategy_bucket_decision(item).as_dict()


def _candidate_row(item: Mapping[str, Any]) -> Dict[str, Any]:
    analysis = item.get("analysis") or {}
    classification = _classification(item)
    evidence_summary = dict(
        classification.get("evidence_summary")
        or item.get("evidence_summary")
        or {}
    )
    return {
        "symbol": item.get("symbol"),
        "strategy_bucket": item.get("strategy_bucket") or UNASSIGNED,
        "bucket_confidence": float(
            classification.get("confidence") or 0.0
        ),
        "bucket_classification_status": (
            classification.get("status") or "unassigned"
        ),
        "bucket_classification_reasons": list(
            classification.get("reasons") or []
        ),
        "bucket_classifier_version": (
            classification.get("classifier_version") or CLASSIFIER_VERSION
        ),
        "proposed_strategy_bucket": classification.get(
            "proposed_bucket"
        ),
        "allows_new_entry": bool(
            classification.get("allows_new_entry")
        ),
        "evidence_gate_passed": bool(
            classification.get("evidence_gate_passed", True)
        ),
        "evidence_summary": evidence_summary,
        "evidence_versions": evidence_summary.get("evidence_versions")
        or {},
        "evidence_statuses": evidence_summary.get("evidence_statuses")
        or {},
        "source_conflicts": evidence_summary.get("source_conflicts")
        or [],
        "final_verdict": (
            analysis.get("final_verdict")
            if isinstance(analysis, Mapping)
            else None
        ),
        "analysis_status": (
            analysis.get("status")
            if isinstance(analysis, Mapping)
            else None
        ),
        "score_breakdown": item.get("score_breakdown"),
    }


def enrich_ranked_candidates_with_buckets(
    ranked: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for item in ranked:
        classification = _classification(item)
        bucket = str(classification.get("bucket") or UNASSIGNED)
        evidence_summary = dict(
            classification.get("evidence_summary") or {}
        )
        next_item = dict(item)
        next_item["strategy_bucket"] = bucket
        next_item["bucket_confidence"] = float(
            classification.get("confidence") or 0.0
        )
        next_item["bucket_classification_status"] = (
            classification.get("status") or "unassigned"
        )
        next_item["bucket_classification_reasons"] = list(
            classification.get("reasons") or []
        )
        next_item["bucket_classifier_version"] = (
            classification.get("classifier_version")
            or CLASSIFIER_VERSION
        )
        next_item["proposed_strategy_bucket"] = classification.get(
            "proposed_bucket"
        )
        next_item["evidence_gate_passed"] = bool(
            classification.get("evidence_gate_passed", True)
        )
        next_item["evidence_summary"] = evidence_summary
        next_item["evidence_versions"] = (
            evidence_summary.get("evidence_versions") or {}
        )
        next_item["evidence_statuses"] = (
            evidence_summary.get("evidence_statuses") or {}
        )
        next_item["source_conflicts"] = (
            evidence_summary.get("source_conflicts") or []
        )
        next_item["strategy_bucket_classification"] = classification

        score_breakdown = dict(next_item.get("score_breakdown") or {})
        score_breakdown["strategy_bucket"] = bucket
        score_breakdown["bucket_confidence"] = next_item[
            "bucket_confidence"
        ]
        score_breakdown["bucket_classification_status"] = next_item[
            "bucket_classification_status"
        ]
        score_breakdown["bucket_classifier_version"] = next_item[
            "bucket_classifier_version"
        ]
        score_breakdown["evidence_gate_passed"] = next_item[
            "evidence_gate_passed"
        ]
        score_breakdown["evidence_versions"] = next_item[
            "evidence_versions"
        ]
        score_breakdown["evidence_statuses"] = next_item[
            "evidence_statuses"
        ]
        next_item["score_breakdown"] = score_breakdown
        enriched.append(next_item)
    return enriched


def build_discover_allocation_plan(
    ranked: List[Dict[str, Any]],
    portfolio_value: Decimal,
) -> Dict[str, Any]:
    enriched = enrich_ranked_candidates_with_buckets(ranked)
    return build_strategy_allocation_plan(enriched, portfolio_value)


def _eligible_for_new_entry(
    item: Mapping[str, Any],
    threshold: Decimal,
) -> bool:
    return (
        item.get("strategy_bucket") in BUCKET_PRIORITY
        and str(item.get("bucket_classification_status") or "")
        == "classified"
        and float(item.get("bucket_confidence") or 0.0)
        >= AUTO_CLASSIFY_THRESHOLD
        and bool(item.get("evidence_gate_passed", True))
        and _score(item) >= threshold
        and _verdict(item) in {"buy", "strong_buy"}
    )


def select_candidates_by_bucket(
    ranked: List[Dict[str, Any]],
    *,
    min_final_score: float = 0.55,
    bucket_limits: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Select only classified candidates that passed the evidence gate."""
    limits = {
        **DEFAULT_BUCKET_SELECTION_LIMITS,
        **(bucket_limits or {}),
    }
    threshold = Decimal(str(min_final_score))
    selected: Dict[str, Any] = {}
    enriched = enrich_ranked_candidates_with_buckets(ranked)

    for bucket in BUCKET_PRIORITY:
        eligible = [
            item
            for item in enriched
            if item.get("strategy_bucket") == bucket
            and _eligible_for_new_entry(item, threshold)
        ]
        eligible = sorted(eligible, key=_score, reverse=True)
        limit = max(0, int(limits.get(bucket, 0)))
        chosen = eligible[:limit]
        selected[bucket] = {
            "limit": limit,
            "eligible_count": len(eligible),
            "selected_count": len(chosen),
            "selected": [_candidate_row(item) for item in chosen],
            "overflow": [
                _candidate_row(item) for item in eligible[limit:]
            ],
        }

    quarantined = [
        item
        for item in enriched
        if item.get("strategy_bucket") == UNASSIGNED
        or not item.get("evidence_gate_passed", True)
    ]
    selected["summary"] = {
        "total_selected": sum(
            selected[bucket]["selected_count"]
            for bucket in BUCKET_PRIORITY
        ),
        "limits": {
            bucket: selected[bucket]["limit"]
            for bucket in BUCKET_PRIORITY
        },
        "min_final_score": min_final_score,
        "auto_classify_threshold": AUTO_CLASSIFY_THRESHOLD,
        "classifier_version": CLASSIFIER_VERSION,
        "quarantine_count": len(quarantined),
        "quarantined_symbols": [
            item.get("symbol") for item in quarantined
        ],
    }
    return selected


def choose_bucket_aware_winner(
    ranked: List[Dict[str, Any]],
    allocation_plan: Optional[Dict[str, Any]] = None,
    *,
    min_final_score: float = 0.55,
) -> Dict[str, Any]:
    """Return a legacy winner only after classification/evidence gates."""
    enriched = enrich_ranked_candidates_with_buckets(ranked)
    by_symbol = {item.get("symbol"): item for item in enriched}
    plan = allocation_plan or build_strategy_allocation_plan(
        enriched,
        Decimal("0"),
    )
    threshold = Decimal(str(min_final_score))

    for bucket in BUCKET_PRIORITY:
        bucket_candidates = (
            ((plan.get("buckets") or {}).get(bucket) or {}).get(
                "candidates"
            )
            or []
        )
        symbols = [
            candidate.get("symbol") for candidate in bucket_candidates
        ]
        candidates = [
            by_symbol[symbol]
            for symbol in symbols
            if symbol in by_symbol
        ]
        candidates = [
            item
            for item in candidates
            if _eligible_for_new_entry(item, threshold)
        ]
        if candidates:
            return sorted(candidates, key=_score, reverse=True)[0]

    eligible = [
        item
        for item in enriched
        if _eligible_for_new_entry(item, threshold)
    ]
    if eligible:
        return sorted(eligible, key=_score, reverse=True)[0]
    return {}


def ranked_response_rows(
    ranked: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows = []
    for index, item in enumerate(
        enrich_ranked_candidates_with_buckets(ranked)
    ):
        row = _candidate_row(item)
        row["rank"] = index + 1
        rows.append(row)
    return rows
