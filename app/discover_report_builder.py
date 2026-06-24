from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from .discover_allocation import (
    build_discover_allocation_plan,
    choose_bucket_aware_winner,
    ranked_response_rows,
    select_candidates_by_bucket,
)


def _selected_symbols(bucket_selection: Dict[str, Any]) -> List[str]:
    symbols: List[str] = []
    for bucket_name, bucket_data in bucket_selection.items():
        if bucket_name == "summary" or not isinstance(bucket_data, dict):
            continue
        for row in bucket_data.get("selected") or []:
            symbol = row.get("symbol")
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def _bucket_candidate(allocation_plan: Dict[str, Any], symbol: str, bucket: str) -> Dict[str, Any]:
    bucket_data = ((allocation_plan.get("buckets") or {}).get(bucket) or {})
    for candidate in bucket_data.get("candidates") or []:
        if str(candidate.get("symbol") or "").upper() == str(symbol or "").upper():
            return candidate
    return {}


def build_selected_positions(
    *,
    ranked: List[Dict[str, Any]],
    allocation_plan: Dict[str, Any],
    bucket_selection: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build the portfolio-first selected_positions contract for Manager.

    This is the new source of truth for discover-analyze-trade. It converts the
    bucket selection output into position-level metadata that Risk and Execution
    can consume for portfolio allocation mode.
    """
    ranked_by_symbol = {str(item.get("symbol") or "").upper(): item for item in ranked}
    selected_positions: List[Dict[str, Any]] = []

    for symbol in _selected_symbols(bucket_selection):
        item = ranked_by_symbol.get(str(symbol).upper())
        if not item:
            continue
        bucket = item.get("strategy_bucket") or (item.get("score_breakdown") or {}).get("strategy_bucket")
        bucket_plan = ((allocation_plan.get("buckets") or {}).get(bucket) or {})
        candidate_meta = _bucket_candidate(allocation_plan, symbol, bucket)
        target_weight = bucket_plan.get("target_weight") or 0
        selected_positions.append(
            {
                "symbol": symbol,
                "bucket": bucket,
                "strategy_bucket": bucket,
                "target_weight": target_weight,
                "allocation_pct": float(target_weight) * 100,
                "target_value": bucket_plan.get("target_value"),
                "suggested_max_value": candidate_meta.get("suggested_max_value") or bucket_plan.get("max_symbol_value"),
                "suggested_equal_weight_value": candidate_meta.get("suggested_equal_weight_value"),
                "final_verdict": (item.get("analysis") or {}).get("final_verdict"),
                "analysis_status": (item.get("analysis") or {}).get("status"),
                "score_breakdown": item.get("score_breakdown"),
                "scanner_candidate": item.get("scanner_candidate"),
            }
        )
    return selected_positions


def build_discover_allocation_report(
    *,
    ranked: List[Dict[str, Any]],
    portfolio_value: Any,
    min_final_score: float,
) -> Dict[str, Any]:
    """Build the allocation view for /discover-analyze-trade.

    Portfolio-first fields:
    - allocation_plan: 50/30/20 policy by bucket
    - bucket_selection: eligible selected rows per bucket
    - selected_positions: multi-position portfolio contract
    - ranked_candidates: full explainability rows

    winner remains only as a backward-compatible legacy field while Manager's
    primary response migrates to selected_positions/allocation_plan.
    """
    allocation_plan = build_discover_allocation_plan(ranked, Decimal(str(portfolio_value or 0)))
    bucket_selection = select_candidates_by_bucket(ranked, min_final_score=min_final_score)
    selected_positions = build_selected_positions(
        ranked=ranked,
        allocation_plan=allocation_plan,
        bucket_selection=bucket_selection,
    )
    return {
        "allocation_plan": allocation_plan,
        "bucket_selection": bucket_selection,
        "selected_positions": selected_positions,
        "winner": choose_bucket_aware_winner(ranked, allocation_plan, min_final_score=min_final_score),
        "ranked_candidates": ranked_response_rows(ranked),
    }
