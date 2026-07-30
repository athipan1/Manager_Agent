#!/usr/bin/env python3
"""Capture a frontend-safe broker snapshot without order identifiers or secrets."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hourly_runtime_loader import runtime  # noqa: E402

JsonHttpClient = runtime.JsonHttpClient
RuntimeSafetyError = runtime.RuntimeSafetyError


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in (value or []) if isinstance(row, Mapping)]


def unwrap(value: Any) -> Any:
    if isinstance(value, Mapping) and "data" in value:
        return value.get("data")
    return value


def bool_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def protection_map(value: Any) -> dict[str, dict[str, Any]]:
    diagnostics = as_dict(unwrap(value))
    return {
        str(row.get("symbol") or "").strip().upper(): row
        for row in as_list(diagnostics.get("positions"))
        if str(row.get("symbol") or "").strip()
    }


def safe_account(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": value.get("status"),
        "cash": value.get("cash") or value.get("cash_balance"),
        "equity": value.get("equity") or value.get("portfolio_value"),
        "buying_power": value.get("buying_power") or value.get("buyingPower"),
    }


def safe_positions(
    rows: Any, protections: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in as_list(rows):
        symbol = str(row.get("symbol") or "").strip().upper()[:16]
        if not symbol:
            continue
        protection = as_dict(protections.get(symbol))
        status = str(protection.get("protection_status") or "unknown")[:48]
        result.append(
            {
                "symbol": symbol,
                "quantity": row.get("quantity") or row.get("qty"),
                "avg_entry_price": row.get("avg_entry_price")
                or row.get("average_cost")
                or row.get("averageCost"),
                "current_price": row.get("current_price")
                or row.get("current_market_price")
                or row.get("market_price"),
                "market_value": row.get("market_value") or row.get("marketValue"),
                "unrealized_pl": row.get("unrealized_pl")
                or row.get("unrealizedPnL"),
                "strategy_bucket": row.get("strategy_bucket")
                or row.get("bucket")
                or "unassigned",
                "protection": {
                    "status": status,
                    "hasStopLoss": bool_value(
                        protection.get("has_protective_stop")
                        or protection.get("stop_covered_qty")
                    ),
                    "hasTakeProfit": bool_value(
                        protection.get("has_take_profit")
                        or protection.get("take_profit_covered_qty")
                    ),
                    "hasBracket": status == "bracket_protected",
                },
            }
        )
    return result


def safe_orders(rows: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in as_list(rows):
        symbol = str(row.get("symbol") or "").strip().upper()[:16]
        if not symbol:
            continue
        result.append(
            {
                "symbol": symbol,
                "side": row.get("side"),
                "quantity": row.get("quantity") or row.get("qty"),
                "order_class": row.get("order_class") or row.get("orderClass"),
                "type": row.get("type") or row.get("order_type"),
                "status": row.get("status") or row.get("broker_status"),
                "limit_price": row.get("limit_price")
                or row.get("take_profit")
                or row.get("takeProfit"),
                "stop_price": row.get("stop_price") or row.get("stop_loss"),
            }
        )
    return result


def build_dashboard_state(
    *,
    preflight: Mapping[str, Any],
    broker_state: Mapping[str, Any],
    protection_diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    runtime_report = as_dict(preflight.get("runtime"))
    protections = protection_map(protection_diagnostics)
    positions = safe_positions(broker_state.get("positions"), protections)
    orders = safe_orders(
        broker_state.get("open_orders") or broker_state.get("orders") or []
    )
    paper = bool_value(runtime_report.get("paper_automation"))
    return {
        "schema_version": "hourly-dashboard-state.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio_cycle_id": preflight.get("portfolio_cycle_id"),
        "market_mode": preflight.get("market_mode"),
        "runtime": {
            "mode": "PAPER" if paper else "SIMULATOR",
            "brokerMode": "ALPACA"
            if paper
            else str(runtime_report.get("broker_mode") or "SIMULATOR").upper(),
            "dryRun": not paper,
            "liveTradingEnabled": False,
        },
        "account": safe_account(as_dict(broker_state.get("account"))),
        "positions": positions,
        "orders": orders,
        "summary": {
            "positionCount": len(positions),
            "openOrderCount": len(orders),
        },
    }


def load_preflight(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeSafetyError("Hourly preflight report is missing or invalid.") from exc
    if not isinstance(payload, dict) or payload.get("status") != "ready":
        raise RuntimeSafetyError("Hourly preflight did not reach ready state.")
    return payload


def capture_dashboard_state(
    *, preflight: Mapping[str, Any], output_path: Path | None = None
) -> dict[str, Any]:
    if preflight.get("status") != "ready":
        raise RuntimeSafetyError("Hourly preflight did not reach ready state.")
    correlation_id = str(
        preflight.get("portfolio_cycle_id") or os.getenv("GITHUB_RUN_ID") or "hourly"
    )
    execution_key = os.getenv("EXECUTION_API_KEY", "").strip()
    client = JsonHttpClient(
        os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006"),
        "Execution_Agent dashboard state",
        {"X-API-KEY": execution_key} if execution_key else {},
        timeout_seconds=30,
    )
    account_id = os.getenv("DEFAULT_ACCOUNT_ID", "1")
    broker_state = as_dict(
        unwrap(
            client.request(
                f"/broker/state?account_id={account_id}",
                correlation_id=correlation_id,
            )
        )
    )
    diagnostics = as_dict(
        unwrap(
            client.request(
                "/broker/protection-diagnostics",
                correlation_id=correlation_id,
            )
        )
    )
    report = build_dashboard_state(
        preflight=preflight,
        broker_state=broker_state,
        protection_diagnostics=diagnostics,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return report


def main() -> int:
    preflight_path = Path(
        os.getenv("HOURLY_PREFLIGHT_REPORT", "reports/hourly-preflight.json")
    )
    output_path = Path(
        os.getenv("HOURLY_DASHBOARD_STATE_REPORT", "reports/hourly-dashboard-state.json")
    )
    try:
        report = capture_dashboard_state(
            preflight=load_preflight(preflight_path), output_path=output_path
        )
        print(
            "Captured frontend-safe broker state: "
            f"positions={report['summary']['positionCount']} "
            f"orders={report['summary']['openOrderCount']}"
        )
        return 0
    except RuntimeSafetyError as exc:
        print(f"Dashboard state capture failed safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
