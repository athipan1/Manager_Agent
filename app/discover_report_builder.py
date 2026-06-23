from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from .discover_allocation import (
    build_discover_allocation_plan,
    choose_bucket_aware_winner,
    ranked_response_rows,
    select_candidates_by_bucket,
)


def build_discover_allocation_report(
    *,
    ranked: List[Dict[str, Any]],
    portfolio_value: Any,
    min_final_score: float,
) -> Dict[str, Any]:
    """Build the allocation view for /discover-analyze-trade.

    This is report-only and intentionally does not submit orders. It prepares:
    - allocation_plan for the 50/30/20 core-satellite policy
    - bucket-aware winner
    - ranked candidate rows with strategy_bucket
    - bucket_selection for future controlled multi-bucket Risk checks
    """
    allocation_plan = build_discover_allocation_plan(ranked, Decimal(str(portfolio_value or 0)))
    winner = choose_bucket_aware_winner(ranked, allocation_plan, min_final_score=min_final_score)
    return {
        "allocation_plan": allocation_plan,
        "bucket_selection": select_candidates_by_bucket(ranked, min_final_score=min_final_score),
        "winner": winner,
        "ranked_candidates": ranked_response_rows(ranked),
    }
