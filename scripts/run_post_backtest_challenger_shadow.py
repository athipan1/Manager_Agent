from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Mapping


MINIMUM_SHADOW_OBSERVATIONS = 100


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _walk(value: Any):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").strip().upper()


def _profile(row: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("execution_context"), Mapping) and row.get("opportunity_score") is not None:
        return _dict(row)
    metadata = _dict(row.get("metadata"))
    details = _dict(metadata.get("details"))
    bundle = _dict(details.get("data_bundle")) or _dict(metadata.get("data_bundle"))
    return _dict(bundle.get("opportunity_profile"))


def _strategy_observations(challenger: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [
        _dict(item)
        for item in challenger.get("shadow_strategy_candidates") or []
        if isinstance(item, Mapping)
        and item.get("broker_order_authorized") is False
        and item.get("risk_execution_authorized") is False
    ]
    if rows:
        return rows
    strategy_id = str(challenger.get("best_strategy_id") or "").strip()
    if not strategy_id:
        return []
    return [
        {
            "rank": 1,
            "strategy_id": strategy_id,
            "strategy_name": challenger.get("best_strategy_name"),
            "score": challenger.get("best_strategy_score"),
            "failed_candidate_oos_gates": challenger.get("failed_candidate_oos_gates")
            or [],
            "observation_only": True,
            "production_promotion_authorized": False,
            "risk_execution_authorized": False,
            "broker_order_authorized": False,
        }
    ]


def build_post_backtest_candidates(
    scanner_report: Mapping[str, Any], challenger_report: Mapping[str, Any]
) -> list[dict[str, Any]]:
    challenger_items = {
        str(item.get("symbol") or "").strip().upper(): _dict(item)
        for item in challenger_report.get("items") or []
        if isinstance(item, Mapping)
        and item.get("challenger_observation_enabled") is True
    }
    if not challenger_items:
        return []

    source_by_symbol: dict[str, dict[str, Any]] = {}
    for row in _walk(scanner_report):
        symbol = _symbol(row)
        if symbol not in challenger_items or symbol in source_by_symbol:
            continue
        profile = _profile(row)
        if not profile:
            continue
        status = str(profile.get("status") or "").strip().lower()
        try:
            score = float(profile.get("opportunity_score"))
        except (TypeError, ValueError):
            continue
        context = _dict(profile.get("execution_context"))
        if (
            status not in {"qualified", "review"}
            or score < 0.50
            or float(context.get("current_price") or 0) <= 0
            or str(context.get("quote_status") or "").lower()
            in {"market_closed", "stale_quote", "missing_quote_timestamp"}
        ):
            continue
        source_by_symbol[symbol] = dict(row)

    candidates: list[dict[str, Any]] = []
    for symbol, challenger in challenger_items.items():
        source = source_by_symbol.get(symbol)
        if source is None:
            continue
        source_profile = _profile(source)
        for strategy in _strategy_observations(challenger):
            strategy_id = str(strategy.get("strategy_id") or "").strip()
            if not strategy_id:
                continue
            candidate = dict(source)
            candidate.update(
                {
                    "symbol": symbol,
                    "status": source_profile.get("status"),
                    "opportunity_score": source_profile.get("opportunity_score"),
                    # Use the immutable Backtest strategy_id so Shadow ledger keys,
                    # Performance aggregation, and Learning evidence distinguish
                    # different parameterizations of the same strategy family.
                    "preferred_strategy_hint": strategy_id,
                    "strategy_affinity": source_profile.get("strategy_affinity") or {},
                    "execution_context": source_profile.get("execution_context") or {},
                    "evidence_quality": source_profile.get("evidence_quality") or {},
                    "reason_code": None,
                }
            )
            metadata = _dict(candidate.get("metadata"))
            metadata["backtest_challenger"] = {
                "lane": "SHADOW_CHALLENGER",
                "observation_only": True,
                "broker_order_authorized": False,
                "production_promotion_authorized": False,
                "strategy_id": strategy_id,
                "strategy_name": strategy.get("strategy_name"),
                "strategy_rank": strategy.get("rank"),
                "strategy_score": strategy.get("score"),
                "candidate_oos_metrics": strategy.get("candidate_oos_metrics") or {},
                "failed_candidate_oos_gates": strategy.get(
                    "failed_candidate_oos_gates"
                )
                or [],
            }
            candidate["metadata"] = metadata
            candidates.append(candidate)
    return candidates


def _post_json(url: str, payload: Mapping[str, Any], *, api_key: str | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-KEY"] = api_key
    request = urllib.request.Request(
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} returned HTTP {exc.code}: {body}") from exc


def run_post_backtest_shadow(
    *,
    scanner_report: Mapping[str, Any],
    challenger_report: Mapping[str, Any],
    cycle_id: str,
    account_id: str = "1",
    manager_url: str = "http://localhost:8000",
    performance_url: str = "http://localhost:8013",
) -> dict[str, Any]:
    candidates = build_post_backtest_candidates(scanner_report, challenger_report)
    if not candidates:
        return {
            "status": "success",
            "candidate_count": 0,
            "symbol_count": 0,
            "strategy_observation_count": 0,
            "shadow": None,
            "performance": None,
            "broker_order_authorized": False,
        }

    correlation_id = f"shadow-backtest-challenger-{cycle_id}"
    shadow = _post_json(
        manager_url.rstrip("/") + "/shadow-trading/hourly",
        {
            "account_id": account_id,
            "correlation_id": correlation_id,
            "cycle_id": cycle_id,
            "candidates": candidates,
            "max_marks": int(os.getenv("SHADOW_MAX_MARKS", "6")),
            "cost_buffer_bps": float(os.getenv("SHADOW_COST_BUFFER_BPS", "2.0")),
        },
    )
    if shadow.get("broker_order_authorized") is not False or int(shadow.get("broker_order_count") or 0) != 0:
        raise RuntimeError("post-Backtest Shadow lane violated broker isolation")

    key = (os.getenv("PERFORMANCE_AGENT_API_KEY") or os.getenv("PROFIT_AGENT_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("PERFORMANCE_AGENT_API_KEY is required")
    performance = _post_json(
        performance_url.rstrip("/") + "/performance/shadow",
        {
            "outcomes": shadow.get("closed_outcomes") or [],
            "minimum_observations_for_paper_review": MINIMUM_SHADOW_OBSERVATIONS,
        },
        api_key=key,
    )
    performance_data = _dict(performance.get("data"))
    if performance_data.get("broker_order_authorized") is not False:
        raise RuntimeError("Performance review unexpectedly authorized broker order")

    symbols = sorted({_symbol(row) for row in candidates if _symbol(row)})
    strategies = sorted(
        {
            str(row.get("preferred_strategy_hint") or "").strip()
            for row in candidates
            if str(row.get("preferred_strategy_hint") or "").strip()
        }
    )
    return {
        "status": "success",
        "candidate_count": len(candidates),
        "symbol_count": len(symbols),
        "strategy_observation_count": len(candidates),
        "symbols": symbols,
        "strategy_ids": strategies,
        "shadow": shadow,
        "performance": performance,
        "broker_order_authorized": False,
    }
