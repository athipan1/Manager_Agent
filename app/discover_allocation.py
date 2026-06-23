from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .portfolio_allocation import (
    CORE_DIVIDEND,
    NEWS_MOMENTUM,
    VALUE_REBOUND,
    build_strategy_allocation_plan,
    classify_strategy_bucket,
)


BUCKET_PRIORITY = (CORE_DIVIDEND, VALUE_REBOUND, NEWS_MOMENTUM)
DEFAULT_BUCKET_SELECTION_LIMITS = {
    CORE_DIVIDEND: 2,
    VALUE_REBOUND: 2,
    NEWS_MOMENTUM: 1,
}


def _score(item: Mapping[str, Any]) -> Decimal:
    try:
        return Decimal(str((item.get("score_breakdown") or {}).get("final_opportunity_score") or 0))
    except Exception:
        return Decimal("0")


def _verdict(item: Mapping[str, Any]) -> str:
    analysis = item.get("analysis") or {}
    if hasattr(analysis, "model_dump"):
        analysis = analysis.model_dump(mode="json")
    if isinstance(analysis, Mapping):
        return str(analysis.get("final_verdict") or "hold").lower()
    return "hold"


def _candidate_row(item: Mapping[str, Any]) -> Dict[str, Any]:
    analysis = item.get("analysis") or {}
    return {
        "symbol": item.get("symbol"),
        "strategy_bucket": item.get("strategy_bucket") or (item.get("score_breakdown") or {}).get("strategy_bucket"),
        "final_verdict": analysis.get("final_verdict") if isinstance(analysis, Mapping) else None,
        "analysis_status": analysis.get("status") if isinstance(analysis, Mapping) else None,
        "score_breakdown": item.get("score_breakdown"),
    }


def enrich_ranked_candidates_with_buckets(ranked: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for item in ranked:
        bucket = classify_strategy_bucket(item)
        next_item = dict(item)
        next_item["strategy_bucket"] = bucket
        score_breakdown = dict(next_item.get("score_breakdown") or {})
        score_breakdown["strategy_bucket"] = bucket
        next_item["score_breakdown"] = score_breakdown
        enriched.append(next_item)
    return enriched


def build_discover_allocation_plan(ranked: List[Dict[str, Any]], portfolio_value: Decimal) -> Dict[str, Any]:
    enriched = enrich_ranked_candidates_with_buckets(ranked)
    return build_strategy_allocation_plan(enriched, portfolio_value)


def select_candidates_by_bucket(
    ranked: List[Dict[str, Any]],
    *,
    min_final_score: float = 0.55,
    bucket_limits: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Select top eligible candidates per strategy bucket.

    This is selection-only. It does not approve, size, or submit orders.
    Defaults: core_dividend=2, value_rebound=2, news_momentum=1.
    """
    limits = {**DEFAULT_BUCKET_SELECTION_LIMITS, **(bucket_limits or {})}
    threshold = Decimal(str(min_final_score))
    selected: Dict[str, Any] = {}
    enriched = enrich_ranked_candidates_with_buckets(ranked)

    for bucket in BUCKET_PRIORITY:
        eligible = [
            item for item in enriched
            if item.get("strategy_bucket") == bucket
            and _score(item) >= threshold
            and _verdict(item) in {"buy", "strong_buy"}
        ]
        eligible = sorted(eligible, key=_score, reverse=True)
        limit = max(0, int(limits.get(bucket, 0)))
        chosen = eligible[:limit]
        selected[bucket] = {
            "limit": limit,
            "eligible_count": len(eligible),
            "selected_count": len(chosen),
            "selected": [_candidate_row(item) for item in chosen],
            "overflow": [_candidate_row(item) for item in eligible[limit:]],
        }

    selected["summary"] = {
        "total_selected": sum(selected[bucket]["selected_count"] for bucket in BUCKET_PRIORITY),
        "limits": {bucket: selected[bucket]["limit"] for bucket in BUCKET_PRIORITY},
        "min_final_score": min_final_score,
    }
    return selected


def choose_bucket_aware_winner(
    ranked: List[Dict[str, Any]],
    allocation_plan: Optional[Dict[str, Any]] = None,
    *,
    min_final_score: float = 0.55,
) -> Dict[str, Any]:
    """
    Pick a single winner while respecting the 50/30/20 bucket structure.

    We still return one winner for the current execution path, but selection becomes
    bucket-aware: choose the best eligible candidate from the highest-priority bucket
    that has candidates. This prepares the flow for future multi-bucket execution.
    """
    enriched = enrich_ranked_candidates_with_buckets(ranked)
    by_symbol = {item.get("symbol"): item for item in enriched}
    plan = allocation_plan or build_strategy_allocation_plan(enriched, Decimal("0"))
    threshold = Decimal(str(min_final_score))

    for bucket in BUCKET_PRIORITY:
        bucket_candidates = (((plan.get("buckets") or {}).get(bucket) or {}).get("candidates") or [])
        symbols = [candidate.get("symbol") for candidate in bucket_candidates]
        candidates = [by_symbol[symbol] for symbol in symbols if symbol in by_symbol]
        candidates = [item for item in candidates if _score(item) >= threshold and _verdict(item) in {"buy", "strong_buy"}]
        if candidates:
            return sorted(candidates, key=_score, reverse=True)[0]

    eligible = [item for item in enriched if _score(item) >= threshold and _verdict(item) in {"buy", "strong_buy"}]
    if eligible:
        return sorted(eligible, key=_score, reverse=True)[0]
    return enriched[0]


def ranked_response_rows(ranked: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for index, item in enumerate(enrich_ranked_candidates_with_buckets(ranked)):
        row = _candidate_row(item)
        row["rank"] = index + 1
        rows.append(row)
    return rows
