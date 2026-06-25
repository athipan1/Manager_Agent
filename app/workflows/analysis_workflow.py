"""Analysis workflow helpers for Manager_Agent.

This module owns Manager-side orchestration of Technical_Agent and
Fundamental_Agent responses. It converts downstream agent envelopes into report
details and builds the weighted final verdict.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..agent_client import call_agents
from ..contracts import StandardAgentResponse
from ..models import ReportDetail, ReportDetails
from ..stock_guard import validate_stock_scope
from ..synthesis import get_reasons, get_weighted_verdict
from ..services.serialization_service import agent_data, normalize_score, response_to_dict


def process_agent_response(
    resp: StandardAgentResponse | Dict[str, Any] | Any,
    agent_type: str,
) -> Optional[ReportDetail]:
    """Convert a downstream agent response into a Manager report detail."""
    resp_dict = response_to_dict(resp)
    if not resp_dict or resp_dict.get("status") != "success":
        return None

    data_obj = agent_data(resp_dict)
    if not data_obj:
        return None

    action = str(data_obj.get("action") or "hold").lower()
    if action not in {"buy", "sell", "hold"}:
        action = "hold"

    score = normalize_score(data_obj.get("confidence_score", 0.0))
    reason = data_obj.get("reason")
    tech_reason, fund_reason = get_reasons(
        action if agent_type == "technical" else "hold",
        action if agent_type == "fundamental" else "hold",
    )

    return ReportDetail(
        action=action,
        score=score,
        reason=reason or (tech_reason if agent_type == "technical" else fund_reason),
    )


async def analyze_single_asset(ticker: str, correlation_id: str) -> Dict[str, Any]:
    """Run technical/fundamental agent analysis for one symbol."""
    validate_stock_scope(ticker)

    tech_response, fund_response = await call_agents(ticker, correlation_id)
    tech_raw = response_to_dict(tech_response)
    fund_raw = response_to_dict(fund_response)

    tech_detail = process_agent_response(tech_raw, "technical")
    fund_detail = process_agent_response(fund_raw, "fundamental")

    if not tech_detail and not fund_detail:
        return {
            "ticker": ticker,
            "error": "All agents failed",
            "raw_data": {
                "technical": tech_raw,
                "fundamental": fund_raw,
            },
        }

    final_verdict = get_weighted_verdict(
        tech_detail.action if tech_detail else "hold",
        tech_detail.score if tech_detail else 0.0,
        fund_detail.action if fund_detail else "hold",
        fund_detail.score if fund_detail else 0.0,
        asset_symbol=ticker,
    )

    return {
        "ticker": ticker,
        "final_verdict": final_verdict,
        "status": "complete" if tech_detail and fund_detail else "partial",
        "details": ReportDetails(technical=tech_detail, fundamental=fund_detail),
        "raw_data": {
            "technical": tech_raw,
            "fundamental": fund_raw,
        },
    }
