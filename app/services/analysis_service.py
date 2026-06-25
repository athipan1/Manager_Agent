"""Pure analysis helper functions for Manager_Agent.

These helpers operate on already-produced analysis payloads. They do not call
Technical_Agent, Fundamental_Agent, Risk_Agent, Database_Agent, or
Execution_Agent.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from .serialization_service import normalize_score


def extract_current_price_and_stop(analysis_result: Dict[str, Any]) -> Tuple[float, Any]:
    """Extract current price and technical stop from a technical agent payload.

    Fails safe to `(0.0, None)` when the expected nested fields are missing or
    malformed.
    """
    tech_dict = analysis_result.get("raw_data", {}).get("technical") or {}
    try:
        data = tech_dict.get("data") or {}
        indicators = data.get("indicators") or {}
        return float(data.get("current_price") or 0), indicators.get("stop_loss")
    except Exception:
        return 0.0, None


def fundamental_v2_scores(analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract normalized fundamental v2 score data from an analysis result."""
    data = (analysis_result.get("raw_data", {}).get("fundamental") or {}).get("data") or {}
    composite = normalize_score(data.get("confidence_score"))
    return {
        "composite_score": composite,
        "sector": data.get("sector"),
        "risk_flags": data.get("risk_flags") or [],
        "comparative_analysis": data.get("comparative_analysis") or {},
    }


def score_deep_analysis(analysis_result: Dict[str, Any], scanner_score: float) -> Dict[str, Any]:
    """Build the manager's discovery ranking score breakdown.

    The formula intentionally mirrors the legacy `app.main._score_deep_analysis`
    helper so this module can be wired in without changing behavior.
    """
    details = analysis_result.get("details")
    tech_detail = details.technical if details else None
    fund_detail = details.fundamental if details else None

    tech_score = normalize_score(tech_detail.score if tech_detail else 0.0)
    fund_score = normalize_score(fund_detail.score if fund_detail else 0.0) or scanner_score
    verdict = analysis_result.get("final_verdict", "hold")
    verdict_score = {
        "strong_buy": 1.0,
        "buy": 0.8,
        "hold": 0.45,
        "sell": 0.1,
        "strong_sell": 0.0,
    }.get(str(verdict).lower(), 0.45)

    final_score = (
        (scanner_score * 0.20)
        + (fund_score * 0.40)
        + (tech_score * 0.30)
        + (verdict_score * 0.10)
    )

    return {
        "scanner_score": round(scanner_score, 4),
        "technical_score": round(tech_score, 4),
        "fundamental_score": round(fund_score, 4),
        "verdict_score": round(verdict_score, 4),
        "final_opportunity_score": round(final_score, 4),
    }
