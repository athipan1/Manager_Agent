import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def unwrap_data(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def first_value(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def number_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_position(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "quantity": number_value(first_value(row.get("quantity"), row.get("qty"))),
        "averageCost": number_value(first_value(row.get("averageCost"), row.get("average_cost"), row.get("avg_entry_price"))),
        "currentPrice": number_value(first_value(row.get("currentPrice"), row.get("current_market_price"), row.get("current_price"))),
        "marketValue": number_value(first_value(row.get("marketValue"), row.get("market_value"))),
        "unrealizedPnL": number_value(first_value(row.get("unrealizedPnL"), row.get("unrealized_pl"))),
        "bucket": first_value(row.get("bucket"), row.get("strategy_bucket"), default="unassigned"),
    }


def safe_order(row: Dict[str, Any]) -> Dict[str, Any]:
    order_class = first_value(row.get("orderClass"), row.get("order_class"), default="unknown")
    return {
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "quantity": number_value(first_value(row.get("quantity"), row.get("qty"))),
        "orderClass": order_class,
        "type": first_value(row.get("type"), row.get("order_type"), default="unknown"),
        "status": first_value(row.get("status"), row.get("broker_status"), default="unknown"),
        "takeProfit": number_value(first_value(row.get("takeProfit"), row.get("take_profit"), row.get("limit_price"), row.get("price"))),
        "stopLoss": bool(first_value(row.get("stopLoss"), row.get("stop_loss"), row.get("stop_price"), order_class == "bracket")),
    }


def safe_curator_signal(row: Dict[str, Any]) -> Dict[str, Any]:
    execution = _dict(row.get("execution"))
    output = _dict(execution.get("output"))
    return {
        "symbol": row.get("symbol"),
        "status": first_value(row.get("status"), execution.get("execution_status"), default="unknown"),
        "skill": first_value(row.get("skill_name"), row.get("skill_id"), default="Curator Signal"),
        "signal": first_value(output.get("signal"), output.get("reason"), row.get("reason"), default="-"),
        "confidence": number_value(first_value(output.get("confidence"), row.get("confidence"), row.get("confidence_score"))),
    }


def build_snapshot(report: Dict[str, Any]) -> Dict[str, Any]:
    response = unwrap_data(report.get("response") or {}) or {}
    if isinstance(response, dict) and "data" in response:
        response = response.get("data") or {}
    response = _dict(response)

    broker_snapshot = _dict(report.get("broker_snapshot"))
    portfolio = _dict(unwrap_data(broker_snapshot.get("portfolio")))
    account = _dict(unwrap_data(broker_snapshot.get("account"))) or _dict(portfolio.get("account"))
    positions = _list(unwrap_data(broker_snapshot.get("positions"))) or _list(portfolio.get("positions"))
    orders = _list(unwrap_data(broker_snapshot.get("orders"))) or _list(portfolio.get("open_orders"))

    protection = _dict(unwrap_data(report.get("protection_diagnostics") or {}))
    protection_rows = {
        str(row.get("symbol") or "").upper(): row
        for row in _list(protection.get("positions"))
        if isinstance(row, dict) and row.get("symbol")
    }

    public_positions = []
    for row in positions:
        if not isinstance(row, dict):
            continue
        item = safe_position(row)
        protection_row = protection_rows.get(str(item.get("symbol") or "").upper(), {})
        item["protection"] = {
            "status": protection_row.get("protection_status"),
            "hasStopLoss": protection_row.get("has_protective_stop"),
            "hasTakeProfit": protection_row.get("has_take_profit"),
            "hasBracket": protection_row.get("has_bracket"),
        }
        public_positions.append(item)

    return {
        "schemaVersion": "dashboard-snapshot.v1",
        "generatedAt": report.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "mode": report.get("mode"),
        "brokerMode": report.get("broker_mode"),
        "flow": report.get("flow"),
        "account": {
            "cash": number_value(first_value(account.get("cash"), account.get("cash_balance"))),
            "equity": number_value(first_value(account.get("equity"), account.get("portfolio_value"))),
            "buyingPower": number_value(first_value(account.get("buying_power"), account.get("buyingPower"))),
            "status": account.get("status"),
            "mode": report.get("mode"),
            "lastSyncedAt": report.get("generated_at"),
        },
        "positions": public_positions,
        "openOrders": [safe_order(row) for row in orders if isinstance(row, dict)],
        "curatorSignals": [safe_curator_signal(row) for row in _list(response.get("curator_signals")) if isinstance(row, dict)],
        "summary": {
            "positionCount": len(public_positions),
            "openOrderCount": len(_list(orders)),
            "curatorSignalCount": len(_list(response.get("curator_signals"))),
            "executionStatus": _dict(response.get("execution")).get("status"),
            "executionReason": _dict(response.get("execution")).get("reason"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a frontend-safe dashboard snapshot JSON.")
    parser.add_argument("--input", default="reports/hourly-auto-trading-report.json")
    parser.add_argument("--output", default="reports/latest-dashboard-snapshot.json")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise FileNotFoundError(f"Missing report file: {input_path}")

    report = json.loads(input_path.read_text(encoding="utf-8"))
    snapshot = build_snapshot(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Wrote dashboard snapshot: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
