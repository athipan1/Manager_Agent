"""Analysis workflow helpers for Manager_Agent.

This module owns Manager-side orchestration of Technical_Agent and
Fundamental_Agent responses. It converts downstream agent envelopes into report
details and builds the weighted final verdict.
"""

from __future__ import annotations

import copy
import os
import threading
import time
from typing import Any, Dict, Optional

from ..agent_client import call_agents
from ..contracts import StandardAgentResponse
from ..models import ReportDetail, ReportDetails
from ..services.serialization_service import (
    agent_data,
    normalize_score,
    response_to_dict,
)
from ..stock_guard import validate_stock_scope
from ..synthesis import get_reasons, get_weighted_verdict


DEEP_ANALYSIS_CACHE_POLICY_VERSION = "manager-deep-analysis-cache-v1"
DEEP_ANALYSIS_RESPONSE_CACHE: Dict[str, Dict[str, Any]] = {}
_DEEP_ANALYSIS_CACHE_LOCK = threading.RLock()
_DEFAULT_DEEP_ANALYSIS_CACHE_TTL_SECONDS = 900.0
_MAX_DEEP_ANALYSIS_CACHE_ENTRIES = 100


def _deep_analysis_cache_ttl_seconds() -> float:
    raw_value = os.getenv(
        "DEEP_ANALYSIS_CACHE_TTL_SECONDS",
        str(_DEFAULT_DEEP_ANALYSIS_CACHE_TTL_SECONDS),
    )
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        return _DEFAULT_DEEP_ANALYSIS_CACHE_TTL_SECONDS


def clear_deep_analysis_cache() -> None:
    """Clear cached deep-analysis results for tests or explicit resets."""

    with _DEEP_ANALYSIS_CACHE_LOCK:
        DEEP_ANALYSIS_RESPONSE_CACHE.clear()


def _cache_key(ticker: str) -> str:
    return str(ticker or "").strip().upper()


def _prune_deep_analysis_cache(now: float) -> None:
    ttl_seconds = _deep_analysis_cache_ttl_seconds()
    expired = [
        key
        for key, row in DEEP_ANALYSIS_RESPONSE_CACHE.items()
        if max(0.0, now - float(row.get("stored_at") or 0.0))
        > ttl_seconds
    ]
    for key in expired:
        DEEP_ANALYSIS_RESPONSE_CACHE.pop(key, None)

    overflow = len(DEEP_ANALYSIS_RESPONSE_CACHE) - _MAX_DEEP_ANALYSIS_CACHE_ENTRIES
    if overflow <= 0:
        return
    oldest = sorted(
        DEEP_ANALYSIS_RESPONSE_CACHE.items(),
        key=lambda item: float(item[1].get("stored_at") or 0.0),
    )
    for key, _ in oldest[:overflow]:
        DEEP_ANALYSIS_RESPONSE_CACHE.pop(key, None)


def _analysis_cache_metadata(
    *,
    hit: bool,
    source_correlation_id: str,
    request_correlation_id: str,
    age_seconds: float = 0.0,
) -> Dict[str, Any]:
    return {
        "policy_version": DEEP_ANALYSIS_CACHE_POLICY_VERSION,
        "hit": hit,
        "one_shot": True,
        "age_seconds": round(max(0.0, age_seconds), 3),
        "ttl_seconds": _deep_analysis_cache_ttl_seconds(),
        "source_correlation_id": source_correlation_id,
        "request_correlation_id": request_correlation_id,
    }


def _get_cached_analysis(
    ticker: str,
    correlation_id: str,
) -> Optional[Dict[str, Any]]:
    key = _cache_key(ticker)
    now = time.monotonic()
    with _DEEP_ANALYSIS_CACHE_LOCK:
        _prune_deep_analysis_cache(now)
        cached = DEEP_ANALYSIS_RESPONSE_CACHE.pop(key, None)
    if not cached:
        return None

    age_seconds = max(0.0, now - float(cached["stored_at"]))
    result = copy.deepcopy(cached["result"])
    result["analysis_cache"] = _analysis_cache_metadata(
        hit=True,
        source_correlation_id=str(cached["source_correlation_id"]),
        request_correlation_id=correlation_id,
        age_seconds=age_seconds,
    )
    return result


def _store_analysis(
    ticker: str,
    correlation_id: str,
    result: Dict[str, Any],
) -> None:
    key = _cache_key(ticker)
    now = time.monotonic()
    with _DEEP_ANALYSIS_CACHE_LOCK:
        _prune_deep_analysis_cache(now)
        DEEP_ANALYSIS_RESPONSE_CACHE[key] = {
            "stored_at": now,
            "source_correlation_id": correlation_id,
            "result": copy.deepcopy(result),
        }
        _prune_deep_analysis_cache(now)


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
        reason=(
            reason
            or (tech_reason if agent_type == "technical" else fund_reason)
        ),
    )


async def analyze_single_asset(
    ticker: str,
    correlation_id: str,
) -> Dict[str, Any]:
    """Run or reuse technical/fundamental analysis for one stock symbol.

    The Hourly workflow intentionally performs discovery twice: Step 19 selects
    symbols for exact Backtests and Step 21 runs fresh portfolio, exposure,
    Backtest, Risk and Execution gates. Scanner responses are already reused by
    ``ScannerAgentClient``. This one-shot cache reuses only the expensive deep
    Technical/Fundamental result while all account and safety gates stay fresh.
    """

    validate_stock_scope(ticker)
    normalized_ticker = _cache_key(ticker)

    cached = _get_cached_analysis(normalized_ticker, correlation_id)
    if cached is not None:
        return cached

    tech_response, fund_response = await call_agents(
        normalized_ticker,
        correlation_id,
    )
    tech_raw = response_to_dict(tech_response)
    fund_raw = response_to_dict(fund_response)

    tech_detail = process_agent_response(tech_raw, "technical")
    fund_detail = process_agent_response(fund_raw, "fundamental")

    if not tech_detail and not fund_detail:
        return {
            "ticker": normalized_ticker,
            "error": "All agents failed",
            "raw_data": {
                "technical": tech_raw,
                "fundamental": fund_raw,
            },
            "analysis_cache": {
                **_analysis_cache_metadata(
                    hit=False,
                    source_correlation_id=correlation_id,
                    request_correlation_id=correlation_id,
                ),
                "stored": False,
                "reason": "all_agents_failed",
            },
        }

    final_verdict = get_weighted_verdict(
        tech_detail.action if tech_detail else "hold",
        tech_detail.score if tech_detail else 0.0,
        fund_detail.action if fund_detail else "hold",
        fund_detail.score if fund_detail else 0.0,
        asset_symbol=normalized_ticker,
    )

    result = {
        "ticker": normalized_ticker,
        "final_verdict": final_verdict,
        "status": "complete" if tech_detail and fund_detail else "partial",
        "details": ReportDetails(
            technical=tech_detail,
            fundamental=fund_detail,
        ),
        "raw_data": {
            "technical": tech_raw,
            "fundamental": fund_raw,
        },
        "analysis_cache": {
            **_analysis_cache_metadata(
                hit=False,
                source_correlation_id=correlation_id,
                request_correlation_id=correlation_id,
            ),
            "stored": True,
        },
    }
    _store_analysis(normalized_ticker, correlation_id, result)
    return result
