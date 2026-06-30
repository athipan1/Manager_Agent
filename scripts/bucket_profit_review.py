from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BUCKET_CONFIG: Dict[str, Dict[str, Any]] = {
    "core_dividend": {
        "frequency": "quarterly",
        "review_title": "Quarterly Core Dividend Review",
        "profit_rules": {
            "first_take_profit_r": 2.0,
            "second_take_profit_r": 3.0,
            "partial_exit_pct": 0.30,
            "trailing_stop_pct": 0.08,
            "break_even_trigger_r": 1.0,
        },
        "checks": [
            "quality_or_dividend_thesis_still_valid",
            "large_trend_reversal_or_drawdown",
            "protective_stop_exists",
            "profit_lock_needed_when_thesis_weakens",
        ],
    },
    "value_rebound": {
        "frequency": "daily",
        "review_title": "Daily Value Rebound Review",
        "profit_rules": {
            "first_take_profit_r": 1.5,
            "second_take_profit_r": 2.25,
            "partial_exit_pct": 0.35,
            "trailing_stop_pct": 0.06,
            "break_even_trigger_r": 1.0,
        },
        "checks": [
            "rebound_thesis_still_valid",
            "value_trap_warning",
            "support_or_stop_breach",
            "partial_profit_after_rebound",
        ],
    },
    "news_momentum": {
        "frequency": "hourly",
        "review_title": "Hourly News Momentum Monitor",
        "profit_rules": {
            "first_take_profit_r": 1.0,
            "second_take_profit_r": 1.75,
            "partial_exit_pct": 0.50,
            "trailing_stop_pct": 0.035,
            "break_even_trigger_r": 0.75,
        },
        "checks": [
            "momentum_still_active",
            "news_or_volume_fading",
            "tight_stop_or_trailing_stop_needed",
            "fast_partial_profit_when_target_hit",
        ],
    },
}


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def _as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _request_json(base_url: str, path: str, *, payload: Any = None, method: str = "GET", api_key: str | None = None, timeout: int = 120) -> Any:
    data = None
    headers: Dict[str, str] = {}
    if api_key:
        headers["X-API-KEY"] = api_key
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "error", "http_status": exc.code, "body": body}
    except Exception as exc:  # pragma: no cover - exercised in workflow resiliency
        return {"status": "error", "error": str(exc)}


def _load_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _positions_from_dashboard(dashboard: Any) -> List[Dict[str, Any]]:
    data = _unwrap(dashboard) or {}
    if not isinstance(data, dict):
        return []
    positions = data.get("positions") or []
    return [p for p in positions if isinstance(p, dict)]


def _positions_from_broker_snapshot(snapshot: Any) -> List[Dict[str, Any]]:
    data = snapshot if isinstance(snapshot, dict) else {}
    positions = _unwrap(data.get("positions")) or []
    return [p for p in positions if isinstance(p, dict)]


def _orders_from_broker_snapshot(snapshot: Any) -> List[Dict[str, Any]]:
    data = snapshot if isinstance(snapshot, dict) else {}
    orders = _unwrap(data.get("orders")) or []
    return [o for o in orders if isinstance(o, dict)]


def _symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").upper()


def _bucket(row: Dict[str, Any]) -> str:
    return str(row.get("strategy_bucket") or row.get("bucket") or row.get("bucket_name") or "unassigned").strip().lower()


def _merge_positions(dashboard_positions: Iterable[Dict[str, Any]], broker_positions: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for source_name, rows in (("dashboard", dashboard_positions), ("broker", broker_positions)):
        for row in rows:
            symbol = _symbol(row)
            if not symbol:
                continue
            existing = merged.setdefault(symbol, {"symbol": symbol})
            existing.setdefault("sources", []).append(source_name)
            existing.update({k: v for k, v in row.items() if v not in (None, "")})
            existing["symbol"] = symbol
    return merged


def _find_stop_order(symbol: str, orders: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for order in orders:
        if _symbol(order) != symbol:
            continue
        side = str(order.get("side") or "").lower()
        order_type = str(order.get("type") or order.get("order_type") or "").lower()
        status = str(order.get("status") or "").lower()
        if side == "sell" and "stop" in order_type and status not in {"canceled", "cancelled", "filled", "expired", "rejected"}:
            return order
    return None


def _position_prices(position: Dict[str, Any], stop_order: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    entry = _as_float(position.get("entry_price") or position.get("avg_entry_price") or position.get("average_entry_price") or position.get("avg_price"))
    current = _as_float(position.get("current_price") or position.get("market_price") or position.get("last_price"))
    if current is None:
        qty = _as_float(position.get("qty") or position.get("quantity"))
        market_value = _as_float(position.get("market_value"))
        if qty and market_value:
            current = market_value / qty
    stop = None
    if stop_order:
        stop = _as_float(stop_order.get("stop_price") or stop_order.get("trigger_price"))
    highest = _as_float(position.get("highest_price_since_entry") or position.get("highest_price")) or current
    risk_per_share = None
    if entry is not None and stop is not None and entry > stop:
        risk_per_share = entry - stop
    return {
        "entry_price": entry,
        "current_price": current,
        "stop_loss": stop,
        "highest_price_since_entry": highest,
        "risk_per_share": risk_per_share,
    }


def build_profit_request(bucket_name: str, position: Dict[str, Any], stop_order: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    prices = _position_prices(position, stop_order)
    quantity = _as_int(position.get("qty") or position.get("quantity"))
    entry = prices["entry_price"]
    current = prices["current_price"]
    unrealized_pl_pct = _as_float(position.get("unrealized_plpc") or position.get("unrealized_pl_pct"))
    if unrealized_pl_pct is None and entry and current:
        unrealized_pl_pct = (current - entry) / entry
    rules = BUCKET_CONFIG[bucket_name]["profit_rules"]
    return {
        "position": {
            "symbol": _symbol(position),
            "quantity": quantity,
            "entry_price": entry or 0,
            "current_price": current or entry or 0,
            "stop_loss": prices["stop_loss"],
            "highest_price_since_entry": prices["highest_price_since_entry"],
            "risk_per_share": prices["risk_per_share"],
            "unrealized_pl_pct": unrealized_pl_pct,
        },
        **rules,
        "exit_on_stop_breach": True,
    }


def fallback_profit_plan(bucket_name: str, position: Dict[str, Any], stop_order: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    symbol = _symbol(position)
    prices = _position_prices(position, stop_order)
    current = prices["current_price"] or 0
    stop = prices["stop_loss"]
    entry = prices["entry_price"] or current
    unrealized_pct = ((current - entry) / entry) if entry else 0
    action = "hold"
    reason = "No bucket review condition triggered by fallback rules"
    confidence = 0.55
    if stop is None:
        action = "move_stop"
        reason = "No active protective stop was found for this open position"
        confidence = 0.70
    elif current <= stop:
        action = "exit_all"
        reason = "Current price is at or below stop loss"
        confidence = 0.90
    elif bucket_name == "news_momentum" and unrealized_pct >= 0.03:
        action = "partial_exit"
        reason = "News momentum position has fast unrealized profit; review partial take-profit"
        confidence = 0.68
    elif bucket_name == "value_rebound" and unrealized_pct >= 0.08:
        action = "partial_exit"
        reason = "Value rebound position has meaningful unrealized profit; review partial take-profit"
        confidence = 0.64
    return {
        "symbol": symbol,
        "primary_action": action,
        "current_r_multiple": None,
        "unrealized_pl_pct": round(unrealized_pct, 6),
        "actions": [
            {
                "action": action,
                "symbol": symbol,
                "quantity": 0,
                "recommended_stop": stop,
                "reason": reason,
                "confidence_score": confidence,
            }
        ],
        "warnings": ["Profit_Agent was unavailable; used Manager_Agent fallback advisory rules"],
        "metadata": {"advisory_only": True, "fallback": True},
    }


def call_profit_agent(profit_agent_url: str, request_payload: Dict[str, Any]) -> Dict[str, Any]:
    response = _request_json(profit_agent_url.rstrip("/"), "/profit/plan", payload=request_payload, method="POST", timeout=60)
    data = _unwrap(response)
    if isinstance(data, dict) and data.get("status") == "error":
        return {"status": "error", "error": data}
    if isinstance(data, dict):
        return data
    return {"status": "error", "error": "unexpected Profit_Agent response", "raw": response}


def review_bucket(bucket_name: str, dashboard: Any, broker_snapshot: Any, profit_agent_url: str | None) -> Dict[str, Any]:
    if bucket_name not in BUCKET_CONFIG:
        raise ValueError(f"unknown bucket: {bucket_name}")
    orders = _orders_from_broker_snapshot(broker_snapshot)
    positions_by_symbol = _merge_positions(_positions_from_dashboard(dashboard), _positions_from_broker_snapshot(broker_snapshot))
    selected = [p for p in positions_by_symbol.values() if _bucket(p) == bucket_name]
    reviewed: List[Dict[str, Any]] = []
    for position in sorted(selected, key=_symbol):
        symbol = _symbol(position)
        stop_order = _find_stop_order(symbol, orders)
        request_payload = build_profit_request(bucket_name, position, stop_order)
        profit_plan = None
        profit_source = "fallback"
        if profit_agent_url:
            profit_plan = call_profit_agent(profit_agent_url, request_payload)
            if profit_plan.get("status") == "error":
                profit_plan = fallback_profit_plan(bucket_name, position, stop_order)
                profit_source = "fallback_after_profit_agent_error"
            else:
                profit_source = "profit_agent"
        else:
            profit_plan = fallback_profit_plan(bucket_name, position, stop_order)
        reviewed.append(
            {
                "symbol": symbol,
                "bucket": bucket_name,
                "quantity": request_payload["position"]["quantity"],
                "entry_price": request_payload["position"]["entry_price"],
                "current_price": request_payload["position"]["current_price"],
                "stop_loss": request_payload["position"].get("stop_loss"),
                "has_protective_stop": stop_order is not None,
                "profit_source": profit_source,
                "profit_request": request_payload,
                "profit_plan": profit_plan,
                "risk_status": "not_submitted",
                "execution_status": "not_submitted",
                "safety": "report_only_no_orders_submitted",
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bucket": bucket_name,
        "config": BUCKET_CONFIG[bucket_name],
        "mode": "BUCKET_PROFIT_REVIEW_REPORT_ONLY",
        "reviewed_positions": reviewed,
        "summary": {
            "positions_seen": len(positions_by_symbol),
            "reviewed_positions": len(reviewed),
            "positions_without_stop": sum(1 for row in reviewed if not row["has_protective_stop"]),
            "profit_agent_used": sum(1 for row in reviewed if row["profit_source"] == "profit_agent"),
            "risk_submissions": 0,
            "execution_submissions": 0,
        },
        "safety": {
            "advisory_only": True,
            "orders_submitted": False,
            "risk_agent_submitted": False,
            "execution_agent_submitted": False,
        },
    }


def render_markdown(report: Dict[str, Any]) -> str:
    config = report.get("config") or {}
    summary = report.get("summary") or {}
    lines = [
        f"# {config.get('review_title', 'Bucket Profit Review')}",
        "",
        f"Generated at UTC: `{report.get('generated_at', '-')}`",
        f"Bucket: `{report.get('bucket', '-')}`",
        f"Frequency: `{config.get('frequency', '-')}`",
        f"Mode: `{report.get('mode', '-')}`",
        "",
        "## Safety",
        "- Advisory only: `true`",
        "- Risk submissions: `0`",
        "- Execution submissions: `0`",
        "- Orders submitted: `false`",
        "",
        "## Summary",
        f"- Positions Seen: `{summary.get('positions_seen', 0)}`",
        f"- Reviewed Positions: `{summary.get('reviewed_positions', 0)}`",
        f"- Positions Without Protective Stop: `{summary.get('positions_without_stop', 0)}`",
        f"- Profit Agent Used: `{summary.get('profit_agent_used', 0)}`",
        "",
        "## Review Checks",
    ]
    for check in config.get("checks") or []:
        lines.append(f"- `{check}`")
    lines.append("")
    reviewed = report.get("reviewed_positions") or []
    lines.append("## Reviewed Positions")
    if not reviewed:
        lines.append("No open positions matched this bucket.")
    else:
        lines.append("| Symbol | Qty | Entry | Current | Stop | Protective Stop | Profit Source | Primary Action | Reason |")
        lines.append("|---|---:|---:|---:|---:|---|---|---|---|")
        for row in reviewed:
            plan = row.get("profit_plan") or {}
            actions = plan.get("actions") or []
            first_action = actions[0] if actions and isinstance(actions[0], dict) else {}
            reason = str(first_action.get("reason") or "-").replace("|", "/")
            lines.append(
                f"| {row.get('symbol', '-')} | {row.get('quantity', '-')} | {row.get('entry_price', '-')} | "
                f"{row.get('current_price', '-')} | {row.get('stop_loss', '-')} | {row.get('has_protective_stop', '-')} | "
                f"{row.get('profit_source', '-')} | {plan.get('primary_action', '-')} | {reason} |"
            )
    lines.extend([
        "",
        "## Raw JSON",
        "```json",
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        "```",
    ])
    return "\n".join(lines)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run report-only bucket profit review for open positions.")
    parser.add_argument("--bucket", choices=sorted(BUCKET_CONFIG), required=True)
    parser.add_argument("--dashboard-url", default=os.getenv("MANAGER_DASHBOARD_URL", "http://localhost/dashboard/data?account_id=1"))
    parser.add_argument("--execution-url", default=os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006"))
    parser.add_argument("--profit-url", default=os.getenv("PROFIT_AGENT_URL", ""))
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
    if args.broker_snapshot_json:
        broker_snapshot = _load_json_file(args.broker_snapshot_json)
    else:
        broker_snapshot = {
            "positions": _request_json(args.execution_url.rstrip("/"), "/positions", api_key=args.execution_api_key),
            "orders": _request_json(args.execution_url.rstrip("/"), "/orders", api_key=args.execution_api_key),
            "account": _request_json(args.execution_url.rstrip("/"), "/account", api_key=args.execution_api_key),
        }
    profit_url = args.profit_url.strip() or None
    report = review_bucket(args.bucket, dashboard, broker_snapshot, profit_url)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(args.output_md.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
