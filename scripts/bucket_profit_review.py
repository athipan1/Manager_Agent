from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BUCKET_CONFIG: Dict[str, Dict[str, Any]] = {
    "core_dividend": {
        "frequency": "quarterly",
        "review_title": "Quarterly Core Dividend Review",
        "profit_rules": {"first_take_profit_r": 2.0, "second_take_profit_r": 3.0, "partial_exit_pct": 0.30, "trailing_stop_pct": 0.08, "break_even_trigger_r": 1.0},
        "checks": ["quality_or_dividend_thesis_still_valid", "large_trend_reversal_or_drawdown", "protective_stop_exists", "profit_lock_needed_when_thesis_weakens"],
    },
    "quality_growth": {
        "frequency": "weekly",
        "review_title": "Weekly Quality Growth Review",
        "profit_rules": {"first_take_profit_r": 2.0, "second_take_profit_r": 3.5, "partial_exit_pct": 0.25, "trailing_stop_pct": 0.10, "break_even_trigger_r": 1.25},
        "checks": ["growth_thesis_still_valid", "quality_metrics_still_strong", "valuation_or_multiple_compression_risk", "trend_damage_or_stop_review", "profit_lock_after_extended_run"],
    },
    "value_rebound": {
        "frequency": "daily",
        "review_title": "Daily Value Rebound Review",
        "profit_rules": {"first_take_profit_r": 1.5, "second_take_profit_r": 2.25, "partial_exit_pct": 0.35, "trailing_stop_pct": 0.06, "break_even_trigger_r": 1.0},
        "checks": ["rebound_thesis_still_valid", "value_trap_warning", "support_or_stop_breach", "partial_profit_after_rebound"],
    },
    "news_momentum": {
        "frequency": "hourly",
        "review_title": "Hourly News Momentum Monitor",
        "profit_rules": {"first_take_profit_r": 1.0, "second_take_profit_r": 1.75, "partial_exit_pct": 0.50, "trailing_stop_pct": 0.035, "break_even_trigger_r": 0.75},
        "checks": ["momentum_still_active", "news_or_volume_fading", "tight_stop_or_trailing_stop_needed", "fast_partial_profit_when_target_hit"],
    },
}
KNOWN_BUCKETS = set(BUCKET_CONFIG)
UNASSIGNED = "unassigned"
HIGHEST_PRICE_FALLBACK_WARNING = "highest_price_since_entry unavailable; used current_price as fallback, trailing stop may be understated"
_NON_DATABASE_PEAK_FIELDS = {"highest_price_since_entry", "highest_price"}


def _unwrap(value: Any) -> Any:
    return value.get("data") if isinstance(value, dict) and "data" in value else value


def _as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return default if value in (None, "") else int(float(value))
    except (TypeError, ValueError):
        return default


def _request_json(base_url: str, path: str, *, payload: Any = None, method: str = "GET", api_key: str | None = None, correlation_id: str | None = None, timeout: int = 120) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers: Dict[str, str] = {"Content-Type": "application/json"} if payload is not None else {}
    if api_key:
        headers["X-API-KEY"] = api_key
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        return {"status": "error", "http_status": exc.code, "body": exc.read().decode("utf-8", errors="replace")}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").upper()


def _normalize_bucket(value: Any) -> str:
    bucket = str(value or "").strip().lower()
    return bucket if bucket in KNOWN_BUCKETS else UNASSIGNED


def _bucket(row: Dict[str, Any]) -> str:
    return _normalize_bucket(row.get("strategy_bucket") or row.get("bucket") or row.get("bucket_name"))


def parse_bucket_hints(value: str | None) -> Dict[str, str]:
    if not value:
        return {}
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        raw = {}
        for part in value.split(","):
            if ":" in part:
                symbol, bucket = part.split(":", 1)
                raw[symbol.strip()] = bucket.strip()
    if not isinstance(raw, dict):
        return {}
    return {str(symbol).upper(): _normalize_bucket(bucket) for symbol, bucket in raw.items() if str(symbol).strip() and _normalize_bucket(bucket) != UNASSIGNED}


def fetch_database_bucket_hints(database_url: str | None, account_id: int | str = 1, api_key: str | None = None) -> Dict[str, str]:
    if not database_url:
        return {}
    response = _request_json(database_url.rstrip("/"), f"/accounts/{account_id}/position-buckets", api_key=api_key, timeout=20)
    data = _unwrap(response)
    if not isinstance(data, list):
        return {}
    hints: Dict[str, str] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        symbol = _symbol(row)
        bucket = _normalize_bucket(row.get("strategy_bucket") or row.get("bucket"))
        if symbol and bucket != UNASSIGNED:
            hints[symbol] = bucket
    return hints


def fetch_database_positions(database_url: str | None, account_id: int | str = 1, api_key: str | None = None) -> List[Dict[str, Any]]:
    if not database_url:
        return []
    response = _request_json(database_url.rstrip("/"), f"/accounts/{account_id}/positions", api_key=api_key, timeout=20)
    data = _unwrap(response)
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict) and _symbol(row)]


def merge_bucket_sources(database_hints: Optional[Dict[str, str]] = None, fallback_hints: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    merged.update(fallback_hints or {})
    merged.update(database_hints or {})
    return {symbol: bucket for symbol, bucket in merged.items() if _normalize_bucket(bucket) != UNASSIGNED}


def _positions_from_dashboard(dashboard: Any) -> List[Dict[str, Any]]:
    data = _unwrap(dashboard) or {}
    return [p for p in (data.get("positions") if isinstance(data, dict) else []) or [] if isinstance(p, dict)]


def _positions_from_broker_snapshot(snapshot: Any) -> List[Dict[str, Any]]:
    data = snapshot if isinstance(snapshot, dict) else {}
    return [p for p in _unwrap(data.get("positions")) or [] if isinstance(p, dict)]


def _orders_from_broker_snapshot(snapshot: Any) -> List[Dict[str, Any]]:
    data = snapshot if isinstance(snapshot, dict) else {}
    return [o for o in _unwrap(data.get("orders")) or [] if isinstance(o, dict)]


def _merge_positions(dashboard_positions: Iterable[Dict[str, Any]], broker_positions: Iterable[Dict[str, Any]], bucket_hints: Optional[Dict[str, str]] = None, database_bucket_hints: Optional[Dict[str, str]] = None, database_positions: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for source_name, rows in (("dashboard", dashboard_positions), ("broker", broker_positions)):
        for row in rows:
            symbol = _symbol(row)
            if symbol:
                current = merged.setdefault(symbol, {"symbol": symbol})
                current.setdefault("sources", []).append(source_name)
                current.update({k: v for k, v in row.items() if v not in (None, "") and k not in _NON_DATABASE_PEAK_FIELDS})
                current["symbol"] = symbol
    for row in database_positions or []:
        symbol = _symbol(row)
        if symbol:
            current = merged.setdefault(symbol, {"symbol": symbol})
            current.setdefault("sources", []).append("database_agent")
            current.update({k: v for k, v in row.items() if v not in (None, "")})
            current["symbol"] = symbol
            current["highest_price_since_entry_source"] = "database_agent" if _as_float(row.get("highest_price_since_entry")) is not None else "database_agent_missing"
            if _bucket(row) != UNASSIGNED:
                current["strategy_bucket_source"] = "database_agent"
    for symbol, bucket in (bucket_hints or {}).items():
        if symbol in merged and _bucket(merged[symbol]) == UNASSIGNED:
            merged[symbol]["strategy_bucket"] = bucket
            merged[symbol]["strategy_bucket_source"] = "bucket_hint"
    for symbol, bucket in (database_bucket_hints or {}).items():
        if symbol in merged:
            merged[symbol]["strategy_bucket"] = bucket
            merged[symbol]["strategy_bucket_source"] = "database_agent"
    return merged


def _find_stop_order(symbol: str, orders: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for row in orders:
        if _symbol(row) == symbol and str(row.get("side") or "").lower() == "sell" and "stop" in str(row.get("type") or row.get("order_type") or "").lower():
            if str(row.get("status") or "").lower() not in {"canceled", "cancelled", "filled", "expired", "rejected"}:
                return row
    return None


def _position_prices(position: Dict[str, Any], stop_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    entry = _as_float(position.get("entry_price") or position.get("avg_entry_price") or position.get("average_entry_price") or position.get("average_cost") or position.get("avg_price"))
    current = _as_float(position.get("current_price") or position.get("current_market_price") or position.get("market_price") or position.get("last_price"))
    if current is None:
        qty, market_value = _as_float(position.get("qty") or position.get("quantity")), _as_float(position.get("market_value"))
        current = market_value / qty if qty and market_value else None
    stop = _as_float((stop_row or {}).get("stop_price") or (stop_row or {}).get("trigger_price")) if stop_row else None
    peak = _as_float(position.get("highest_price_since_entry"))
    warnings: List[str] = []
    peak_source = position.get("highest_price_since_entry_source") or "database_agent"
    if peak is None:
        peak = current
        peak_source = "current_price_fallback"
        warnings.append(HIGHEST_PRICE_FALLBACK_WARNING)
    return {"entry_price": entry, "current_price": current, "stop_loss": stop, "highest_price_since_entry": peak, "highest_price_since_entry_source": peak_source, "warnings": warnings, "risk_per_share": (entry - stop) if entry and stop and entry > stop else None}


def _profit_lifecycle(position: Dict[str, Any], quantity: int) -> Optional[Dict[str, Any]]:
    if "database_agent" not in (position.get("sources") or []):
        return None
    raw_position_id = position.get("position_id")
    account_id = position.get("account_id")
    version = _as_int(position.get("position_version"), 0)
    if raw_position_id in (None, "") or account_id in (None, "") or version < 1:
        return None
    position_id = str(raw_position_id)
    if position_id.isdigit():
        position_id = f"account-{account_id}:position-{position_id}"
    return {
        "position_id": position_id,
        "position_version": version,
        "first_target_executed": bool(position.get("first_target_executed", False)),
        "second_target_executed": bool(position.get("second_target_executed", False)),
        "total_exited_quantity": _as_float(position.get("total_exited_quantity"), 0) or 0,
        "remaining_quantity": quantity,
    }


def build_profit_request(bucket_name: str, position: Dict[str, Any], stop_order: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    prices = _position_prices(position, stop_order)
    entry, current = prices["entry_price"], prices["current_price"]
    quantity = _as_int(position.get("qty") or position.get("quantity"))
    unrealized_pct = _as_float(position.get("unrealized_plpc") or position.get("unrealized_pl_pct"))
    if unrealized_pct is None and entry and current:
        unrealized_pct = (current - entry) / entry
    payload = {"schema_version": "profit-decision.v2", "position": {"symbol": _symbol(position), "quantity": quantity, "entry_price": entry or 0, "current_price": current or entry or 0, "stop_loss": prices["stop_loss"], "highest_price_since_entry": prices["highest_price_since_entry"], "risk_per_share": prices["risk_per_share"], "unrealized_pl_pct": unrealized_pct}, **BUCKET_CONFIG[bucket_name]["profit_rules"], "exit_on_stop_breach": True, "warnings": list(prices["warnings"]), "metadata": {"highest_price_since_entry_source": prices["highest_price_since_entry_source"], "cross_repo_fix_part": 3}}
    lifecycle = _profit_lifecycle(position, quantity)
    if lifecycle is not None:
        payload["lifecycle"] = lifecycle
    return payload


def fallback_profit_plan(bucket_name: str, position: Dict[str, Any], stop_order: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    symbol = _symbol(position)
    prices = _position_prices(position, stop_order)
    current, stop, entry = prices["current_price"] or 0, prices["stop_loss"], prices["entry_price"] or prices["current_price"] or 0
    unrealized_pct = ((current - entry) / entry) if entry else 0
    action, reason, confidence = "hold", "No bucket review condition triggered by fallback rules", 0.55
    if stop is None:
        action, reason, confidence = "move_stop", "No active protective stop was found for this open position", 0.70
    elif current <= stop:
        action, reason, confidence = "exit_all", "Current price is at or below stop loss", 0.90
    elif bucket_name == "news_momentum" and unrealized_pct >= 0.03:
        action, reason, confidence = "partial_exit", "News momentum position has fast unrealized profit; review partial take-profit", 0.68
    elif bucket_name == "value_rebound" and unrealized_pct >= 0.08:
        action, reason, confidence = "partial_exit", "Value rebound position has meaningful unrealized profit; review partial take-profit", 0.64
    elif bucket_name == "quality_growth" and unrealized_pct >= 0.15:
        action, reason, confidence = "partial_exit", "Quality growth position has extended unrealized profit; review modest partial take-profit", 0.62
    warnings = ["Profit_Agent was unavailable; used Manager_Agent fallback advisory rules", *prices["warnings"]]
    return {"symbol": symbol, "primary_action": action, "current_r_multiple": None, "unrealized_pl_pct": round(unrealized_pct, 6), "actions": [{"action": action, "symbol": symbol, "quantity": 0, "recommended_stop": stop, "reason": reason, "confidence_score": confidence}], "warnings": warnings, "metadata": {"advisory_only": True, "fallback": True, "highest_price_since_entry_source": prices["highest_price_since_entry_source"]}}


def call_profit_agent(
    profit_agent_url: str,
    request_payload: Dict[str, Any],
    api_key: str | None = None,
    correlation_id: str | None = None,
) -> Dict[str, Any]:
    response = _request_json(
        profit_agent_url.rstrip("/"),
        "/profit/plan",
        payload=request_payload,
        method="POST",
        api_key=api_key,
        correlation_id=correlation_id,
        timeout=60,
    )
    if isinstance(response, dict) and response.get("status") == "success":
        response_correlation_id = response.get("correlation_id")
        if response_correlation_id not in {None, correlation_id}:
            return {"status": "error", "error": "Profit_Agent correlation_id mismatch"}
    data = _unwrap(response)
    if isinstance(data, dict) and isinstance(response, dict):
        schema_version = str(response.get("schema_version") or "profit-plan.v1")
        if schema_version != "profit-decision.v2":
            warnings = list(data.get("warnings") or [])
            warnings.append(
                f"deprecated Profit_Agent schema {schema_version}; migrate to profit-decision.v2"
            )
            data["warnings"] = list(dict.fromkeys(warnings))
    if isinstance(data, dict) and data.get("status") == "error":
        return {"status": "error", "error": data}
    return data if isinstance(data, dict) else {"status": "error", "error": "unexpected Profit_Agent response", "raw": response}


def _bucket_distribution(positions: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    output: Dict[str, int] = {}
    for row in positions.values():
        output[_bucket(row)] = output.get(_bucket(row), 0) + 1
    return dict(sorted(output.items()))


def review_bucket(bucket_name: str, dashboard: Any, broker_snapshot: Any, profit_agent_url: str | None, bucket_hints: Optional[Dict[str, str]] = None, database_bucket_hints: Optional[Dict[str, str]] = None, database_positions: Optional[Iterable[Dict[str, Any]]] = None, profit_api_key: str | None = None, correlation_id: str | None = None) -> Dict[str, Any]:
    if bucket_name not in BUCKET_CONFIG:
        raise ValueError(f"unknown bucket: {bucket_name}")
    rows_by_symbol = _merge_positions(_positions_from_dashboard(dashboard), _positions_from_broker_snapshot(broker_snapshot), bucket_hints, database_bucket_hints, database_positions)
    orders = _orders_from_broker_snapshot(broker_snapshot)
    review_correlation_id = correlation_id or str(uuid.uuid4())
    reviewed: List[Dict[str, Any]] = []
    for position in sorted([p for p in rows_by_symbol.values() if _bucket(p) == bucket_name], key=_symbol):
        stop_row = _find_stop_order(_symbol(position), orders)
        request_payload = build_profit_request(bucket_name, position, stop_row)
        request_warnings = list(request_payload.get("warnings") or [])
        if profit_agent_url:
            plan = call_profit_agent(
                profit_agent_url,
                request_payload,
                profit_api_key,
                review_correlation_id,
            )
            source = "profit_agent" if plan.get("status") != "error" else "fallback_after_profit_agent_error"
            if plan.get("status") == "error":
                plan = fallback_profit_plan(bucket_name, position, stop_row)
        else:
            plan, source = fallback_profit_plan(bucket_name, position, stop_row), "fallback"
        plan_warnings = list(plan.get("warnings") or [])
        for warning in request_warnings:
            if warning not in plan_warnings:
                plan_warnings.append(warning)
        plan["warnings"] = plan_warnings
        reviewed.append({"symbol": _symbol(position), "bucket": bucket_name, "bucket_source": position.get("strategy_bucket_source") or "position_data", "quantity": request_payload["position"]["quantity"], "entry_price": request_payload["position"]["entry_price"], "current_price": request_payload["position"]["current_price"], "stop_loss": request_payload["position"].get("stop_loss"), "highest_price_since_entry": request_payload["position"].get("highest_price_since_entry"), "highest_price_since_entry_source": request_payload.get("metadata", {}).get("highest_price_since_entry_source"), "warnings": request_warnings, "has_protective_stop": stop_row is not None, "profit_source": source, "profit_request": request_payload, "profit_plan": plan, "risk_status": "not_submitted", "execution_status": "not_submitted", "safety": "report_only_no_orders_submitted"})
    report_warnings = sorted({warning for row in reviewed for warning in row.get("warnings", []) if warning})
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "correlation_id": review_correlation_id, "bucket": bucket_name, "config": BUCKET_CONFIG[bucket_name], "mode": "BUCKET_PROFIT_REVIEW_REPORT_ONLY", "bucket_hints": bucket_hints or {}, "database_bucket_hints": database_bucket_hints or {}, "bucket_distribution": _bucket_distribution(rows_by_symbol), "warnings": report_warnings, "reviewed_positions": reviewed, "summary": {"positions_seen": len(rows_by_symbol), "reviewed_positions": len(reviewed), "positions_without_protective_stop": sum(1 for row in reviewed if not row["has_protective_stop"]), "positions_without_stop": sum(1 for row in reviewed if not row["has_protective_stop"]), "position_peak_fallbacks": sum(1 for row in reviewed if row.get("highest_price_since_entry_source") == "current_price_fallback"), "bucket_hints_applied": sum(1 for row in rows_by_symbol.values() if row.get("strategy_bucket_source") == "bucket_hint"), "database_bucket_hints_applied": sum(1 for row in rows_by_symbol.values() if row.get("strategy_bucket_source") == "database_agent"), "profit_agent_used": sum(1 for row in reviewed if row["profit_source"] == "profit_agent"), "risk_submissions": 0, "execution_submissions": 0}, "safety": {"advisory_only": True, "orders_submitted": False, "risk_agent_submitted": False, "execution_agent_submitted": False}}


def render_markdown(report: Dict[str, Any]) -> str:
    config, summary = report.get("config") or {}, report.get("summary") or {}
    lines = [f"# {config.get('review_title', 'Bucket Profit Review')}", "", f"Generated at UTC: `{report.get('generated_at', '-')}`", f"Bucket: `{report.get('bucket', '-')}`", f"Frequency: `{config.get('frequency', '-')}`", f"Mode: `{report.get('mode', '-')}`", "", "## Safety", "- Advisory only: `true`", "- Risk submissions: `0`", "- Execution submissions: `0`", "- Orders submitted: `false`", "", "## Summary", f"- Positions Seen: `{summary.get('positions_seen', 0)}`", f"- Reviewed Positions: `{summary.get('reviewed_positions', 0)}`", f"- Positions Without Protective Stop: `{summary.get('positions_without_protective_stop', summary.get('positions_without_stop', 0))}`", f"- Position Peak Fallbacks: `{summary.get('position_peak_fallbacks', 0)}`", f"- Database Bucket Hints Applied: `{summary.get('database_bucket_hints_applied', 0)}`", f"- Fallback Bucket Hints Applied: `{summary.get('bucket_hints_applied', 0)}`", f"- Profit Agent Used: `{summary.get('profit_agent_used', 0)}`"]
    if report.get("warnings"):
        lines.extend(["", "## Warnings", *[f"- {warning}" for warning in report["warnings"]]])
    lines.extend(["", "## Bucket Distribution", "```json", json.dumps(report.get("bucket_distribution") or {}, ensure_ascii=False, indent=2, default=str), "```", "", "## Review Checks"])
    for check in config.get("checks") or []:
        lines.append(f"- `{check}`")
    lines.extend(["", "## Reviewed Positions"])
    reviewed = report.get("reviewed_positions") or []
    if not reviewed:
        lines.append("No open positions matched this bucket.")
    else:
        lines.append("| Symbol | Bucket Source | Qty | Entry | Current | Peak | Peak Source | Stop | Protective Stop | Profit Source | Primary Action | Reason |")
        lines.append("|---|---|---:|---:|---:|---:|---|---:|---|---|---|---|")
        for row in reviewed:
            plan = row.get("profit_plan") or {}
            actions = plan.get("actions") or []
            first_action = actions[0] if actions and isinstance(actions[0], dict) else {}
            reason = str(first_action.get("reason") or "-").replace("|", "/")
            lines.append(f"| {row.get('symbol', '-')} | {row.get('bucket_source', '-')} | {row.get('quantity', '-')} | {row.get('entry_price', '-')} | {row.get('current_price', '-')} | {row.get('highest_price_since_entry', '-')} | {row.get('highest_price_since_entry_source', '-')} | {row.get('stop_loss', '-')} | {row.get('has_protective_stop', '-')} | {row.get('profit_source', '-')} | {plan.get('primary_action', '-')} | {reason} |")
    lines.extend(["", "## Raw JSON", "```json", json.dumps(report, ensure_ascii=False, indent=2, default=str), "```"])
    return "\n".join(lines)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run report-only bucket profit review for open positions.")
    parser.add_argument("--bucket", choices=sorted(BUCKET_CONFIG), required=True)
    parser.add_argument("--dashboard-url", default=os.getenv("MANAGER_DASHBOARD_URL", "http://localhost/dashboard/data?account_id=1"))
    parser.add_argument("--execution-url", default=os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006"))
    parser.add_argument("--profit-url", default=os.getenv("PROFIT_AGENT_URL", ""))
    parser.add_argument("--profit-api-key", default=os.getenv("PROFIT_AGENT_API_KEY", ""))
    parser.add_argument("--correlation-id", default=os.getenv("CORRELATION_ID", ""))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_AGENT_URL", ""))
    parser.add_argument("--database-api-key", default=os.getenv("DATABASE_AGENT_API_KEY", ""))
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument("--bucket-hints", default=os.getenv("BUCKET_REVIEW_BUCKET_HINTS", ""))
    parser.add_argument("--execution-api-key", default=os.getenv("EXECUTION_API_KEY", "dev_execution_key"))
    parser.add_argument("--dashboard-json", type=Path, default=None)
    parser.add_argument("--broker-snapshot-json", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=Path("reports/bucket-profit-review.json"))
    parser.add_argument("--output-md", type=Path, default=Path("reports/bucket-profit-review.md"))
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.dashboard_json:
        dashboard = _load_json_file(args.dashboard_json)
    else:
        base, path = args.dashboard_url.split("/dashboard", 1)
        dashboard = _request_json(base, f"/dashboard{path}")
    broker_snapshot = _load_json_file(args.broker_snapshot_json) if args.broker_snapshot_json else {"positions": _request_json(args.execution_url.rstrip("/"), "/positions", api_key=args.execution_api_key), "orders": _request_json(args.execution_url.rstrip("/"), "/orders", api_key=args.execution_api_key), "account": _request_json(args.execution_url.rstrip("/"), "/account", api_key=args.execution_api_key)}
    fallback_hints = parse_bucket_hints(args.bucket_hints)
    database_url = args.database_url.strip() or None
    database_api_key = args.database_api_key.strip() or None
    database_positions = fetch_database_positions(database_url, args.account_id, database_api_key)
    database_hints = fetch_database_bucket_hints(database_url, args.account_id, database_api_key)
    report = review_bucket(args.bucket, dashboard, broker_snapshot, args.profit_url.strip() or None, bucket_hints=fallback_hints, database_bucket_hints=database_hints, database_positions=database_positions, profit_api_key=args.profit_api_key.strip() or None, correlation_id=args.correlation_id.strip() or None)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(args.output_md.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
