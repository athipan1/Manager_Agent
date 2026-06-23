from __future__ import annotations

import httpx
from functools import wraps
from typing import Any, Dict, List, Union

from . import config
from .database_client import DatabaseAgentClient
from .execution_client import ExecutionAgentClient
from .risk_agent_client import RISK_AGENT_URL, RISK_AGENT_TIMEOUT
from .stock_guard import stock_guard_status, validate_stock_scope


async def _check_database(db_client: DatabaseAgentClient, account_id: Union[int, str], correlation_id: str, sample_symbol: str) -> Dict[str, Any]:
    try:
        await db_client.health(correlation_id)
        await db_client.get_session_risk_snapshot(account_id, correlation_id, symbol=sample_symbol)
        return {"status": "pass", "details": "Database health and session risk snapshot available."}
    except Exception as exc:
        return {"status": "fail", "details": str(exc)}


async def _check_execution(correlation_id: str) -> Dict[str, Any]:
    try:
        async with ExecutionAgentClient() as client:
            await client.health(correlation_id)
        return {"status": "pass", "details": "Execution Agent health endpoint available."}
    except Exception as exc:
        return {"status": "fail", "details": str(exc)}


async def _check_broker_reconciliation(account_id: Union[int, str], correlation_id: str) -> Dict[str, Any]:
    try:
        async with ExecutionAgentClient() as client:
            result = await client.reconcile_broker_state(account_id, correlation_id, push_to_database=config.BROKER_RECONCILE_PUSH_TO_DATABASE)
        payload = result.data if isinstance(result.data, dict) else {}
        ok = bool(payload.get("ok", False))
        database_sync = payload.get("database_sync") or {}
        broker_state = payload.get("broker_state") or {}
        summary = broker_state.get("summary") or {}
        status = "pass" if ok else "warn"
        if config.BROKER_RECONCILE_REQUIRED and not ok:
            status = "fail"
        return {
            "status": status,
            "details": "Broker reconciliation completed." if ok else "Broker reconciliation returned non-ok status.",
            "database_sync_status": database_sync.get("status"),
            "position_count": summary.get("position_count"),
            "open_order_count": summary.get("open_order_count"),
            "stale_order_count": summary.get("stale_order_count"),
            "buying_power_unavailable": summary.get("buying_power_unavailable"),
            "cash_negative": summary.get("cash_negative"),
        }
    except Exception as exc:
        return {"status": "fail" if config.BROKER_RECONCILE_REQUIRED else "warn", "details": str(exc)}


async def _check_risk() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(base_url=RISK_AGENT_URL, timeout=RISK_AGENT_TIMEOUT) as client:
            response = await client.get("/health")
            response.raise_for_status()
        return {"status": "pass", "details": "Risk Agent health endpoint available."}
    except Exception as exc:
        return {"status": "fail", "details": str(exc)}


def _check_config() -> Dict[str, Any]:
    checks = {
        "trading_mode_valid": config.TRADING_MODE in {"PAPER", "LIVE"},
        "live_allowed_when_live": config.TRADING_MODE != "LIVE" or config.ALLOW_LIVE_TRADING,
        "trading_enabled": bool(config.TRADING_ENABLED),
        "emergency_halt_off": not bool(config.MANAGER_EMERGENCY_HALT),
        "manual_approval_flag_known": isinstance(config.MANUAL_APPROVAL_REQUIRED, bool),
        "broker_reconcile_before_execution": bool(config.BROKER_RECONCILE_BEFORE_EXECUTION),
    }
    return {"status": "pass" if all(checks.values()) else "fail", "checks": checks}


async def run_stock_live_preflight(account_id: Union[int, str], sample_symbol: str, correlation_id: str) -> Dict[str, Any]:
    sample_symbol = str(sample_symbol or "AAPL").upper()
    stock_guard = stock_guard_status(sample_symbol)
    try:
        validate_stock_scope(sample_symbol)
        stock_status = {"status": "pass", **stock_guard}
    except Exception as exc:
        stock_status = {"status": "fail", **stock_guard, "details": str(exc)}

    async with DatabaseAgentClient() as db_client:
        checks = {
            "config": _check_config(),
            "stock_guard": stock_status,
            "database": await _check_database(db_client, account_id, correlation_id, sample_symbol),
            "risk_agent": await _check_risk(),
            "execution_agent": await _check_execution(correlation_id),
            "broker_reconciliation": await _check_broker_reconciliation(account_id, correlation_id),
        }
    approved = all(item.get("status") == "pass" for item in checks.values())
    return {
        "approved": approved,
        "reason": "stock live preflight passed" if approved else "one or more stock live preflight checks failed",
        "account_id": account_id,
        "sample_symbol": sample_symbol,
        "trading_mode": config.TRADING_MODE,
        "manual_approval_required": config.MANUAL_APPROVAL_REQUIRED,
        "checks": checks,
    }


def _response_data(response: Any) -> Dict[str, Any] | None:
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return data
    if isinstance(response, dict):
        data = response.get("data")
        return data if isinstance(data, dict) else None
    return None


def _ranked_rows_to_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for row in rows or []:
        symbol = row.get("symbol")
        if not symbol:
            continue
        items.append({
            "symbol": symbol,
            "analysis": {"ticker": symbol, "final_verdict": row.get("final_verdict") or "hold", "status": row.get("analysis_status"), "details": {}},
            "scanner_candidate": row.get("scanner_candidate") or {},
            "score_breakdown": dict(row.get("score_breakdown") or {}),
        })
    return items


def _attach_discover_allocation_response(response: Any) -> Any:
    data = _response_data(response)
    if not data or data.get("flow") != "discover_analyze_trade" or data.get("allocation_plan"):
        return response
    try:
        from .discover_report_builder import build_discover_allocation_report
        items = _ranked_rows_to_items(data.get("ranked_candidates") or [])
        if not items:
            return response
        report = build_discover_allocation_report(ranked=items, portfolio_value=0, min_final_score=0)
        data["allocation_plan"] = report.get("allocation_plan")
        data["ranked_candidates"] = report.get("ranked_candidates") or data.get("ranked_candidates")
        winner = data.get("winner") or {}
        patched_winner = report.get("winner") or {}
        winner["strategy_bucket"] = patched_winner.get("strategy_bucket") or (patched_winner.get("score_breakdown") or {}).get("strategy_bucket")
        data["winner"] = winner
    except Exception:
        return response
    return response


def _install_discover_allocation_response_patch() -> None:
    try:
        from fastapi import FastAPI
    except Exception:
        return
    if getattr(FastAPI, "_discover_allocation_response_patch", False):
        return
    original_add_api_route = FastAPI.add_api_route

    def patched_add_api_route(self, path, endpoint, *args, **kwargs):
        if path == "/discover-analyze-trade":
            original_endpoint = endpoint

            @wraps(original_endpoint)
            async def wrapped_endpoint(*endpoint_args, **endpoint_kwargs):
                return _attach_discover_allocation_response(await original_endpoint(*endpoint_args, **endpoint_kwargs))

            endpoint = wrapped_endpoint
        return original_add_api_route(self, path, endpoint, *args, **kwargs)

    FastAPI.add_api_route = patched_add_api_route
    FastAPI._discover_allocation_response_patch = True


_install_discover_allocation_response_patch()
