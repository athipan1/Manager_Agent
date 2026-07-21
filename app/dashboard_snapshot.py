from __future__ import annotations

import datetime
import os
from typing import Any, Dict, Iterable, List

from .contracts.dashboard import (
    DashboardAccount,
    DashboardCuratorSignal,
    DashboardOrder,
    DashboardPosition,
    DashboardProtection,
    DashboardSnapshot,
    DashboardSummary,
)


def _dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _first(*values: Any, default: Any = None) -> Any:
    return next((value for value in values if value not in (None, "")), default)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _boolean(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _timestamp(value: Any) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.datetime.now(datetime.timezone.utc)
    else:
        parsed = datetime.datetime.now(datetime.timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _protection_for(symbol: str, orders: Iterable[Dict[str, Any]], row: Dict[str, Any]) -> DashboardProtection:
    explicit = _dict(row.get("protection"))
    symbol_orders = [order for order in orders if str(order.get("symbol") or "").upper() == symbol.upper()]
    has_bracket = _boolean(explicit.get("hasBracket")) or any(
        str(order.get("order_class") or order.get("orderClass") or "").lower() == "bracket"
        for order in symbol_orders
    )
    has_stop = _boolean(explicit.get("hasStopLoss")) or has_bracket or any(
        bool(order.get("stop_price") or order.get("stop_loss") or order.get("stopLoss"))
        for order in symbol_orders
    )
    has_take_profit = _boolean(explicit.get("hasTakeProfit")) or has_bracket or any(
        bool(order.get("limit_price") or order.get("take_profit") or order.get("takeProfit"))
        for order in symbol_orders
    )
    status = str(explicit.get("status") or ("bracket_protected" if has_bracket else "protected" if has_stop else "unprotected"))
    return DashboardProtection(
        status=status,
        hasStopLoss=has_stop,
        hasTakeProfit=has_take_profit,
        hasBracket=has_bracket,
    )


def _safe_position(row: Any, orders: List[Dict[str, Any]]) -> DashboardPosition | None:
    item = _dict(row)
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    return DashboardPosition(
        symbol=symbol,
        quantity=_number(_first(item.get("quantity"), item.get("qty"))),
        averageCost=_number(_first(item.get("averageCost"), item.get("average_cost"), item.get("avg_entry_price"))),
        currentPrice=_number(_first(item.get("currentPrice"), item.get("current_market_price"), item.get("current_price"))),
        marketValue=_number(_first(item.get("marketValue"), item.get("market_value"), item.get("value"))),
        unrealizedPnL=_number(_first(item.get("unrealizedPnL"), item.get("unrealized_pl"))),
        bucket=str(_first(item.get("bucket"), item.get("strategy_bucket"), default="unassigned")),
        protection=_protection_for(symbol, orders, item),
    )


def _safe_order(row: Any) -> DashboardOrder | None:
    item = _dict(row)
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    order_class = str(_first(item.get("orderClass"), item.get("order_class"), default="unknown"))
    return DashboardOrder(
        symbol=symbol,
        side=str(_first(item.get("side"), default="unknown")),
        quantity=_number(_first(item.get("quantity"), item.get("qty"))),
        orderClass=order_class,
        type=str(_first(item.get("type"), item.get("order_type"), default="unknown")),
        status=str(_first(item.get("status"), item.get("broker_status"), item.get("order_status"), default="unknown")),
        takeProfit=_number(_first(item.get("takeProfit"), item.get("take_profit"), item.get("limit_price"), item.get("price"))),
        stopLoss=_boolean(_first(item.get("stopLoss"), item.get("stop_loss"), item.get("stop_price"), order_class.lower() == "bracket")),
    )


def _safe_signal(row: Any) -> DashboardCuratorSignal | None:
    item = _dict(row)
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    output = _dict(item.get("output"))
    confidence = max(0.0, min(1.0, _number(_first(item.get("confidence"), item.get("confidence_score"), output.get("confidence")))))
    return DashboardCuratorSignal(
        symbol=symbol,
        status=str(_first(item.get("status"), item.get("execution_status"), default="unknown")),
        skill=str(_first(item.get("skill"), item.get("skill_name"), default="Curator Signal")),
        signal=str(_first(item.get("signal"), item.get("reason"), output.get("signal"), default="-")),
        confidence=confidence,
    )


def build_dashboard_snapshot(payload: Dict[str, Any]) -> DashboardSnapshot:
    """Map operational state to a strict, browser-safe whitelist."""
    data = _dict(payload)
    balance = _dict(data.get("balance"))
    orders = [_dict(order) for order in _list(data.get("open_orders"))]
    positions = [item for row in _list(data.get("positions")) if (item := _safe_position(row, orders)) is not None]
    public_orders = [item for row in orders if (item := _safe_order(row)) is not None]
    signals = [item for row in _list(data.get("curator_signals")) if (item := _safe_signal(row)) is not None]
    raw_summary = _dict(data.get("summary"))
    generated_at = _timestamp(_first(data.get("generated_at"), data.get("generatedAt")))
    mode = os.getenv("TRADING_MODE", "PAPER").strip().upper() or "PAPER"
    broker_mode = os.getenv("BROKER_MODE", "SIMULATOR").strip().upper() or "SIMULATOR"
    problem_count = int(_number(_first(raw_summary.get("problem_count"), len(_list(data.get("problems"))))))
    data_source = str(data.get("data_source") or "unavailable")
    degraded = problem_count > 0 or data_source == "unavailable"

    return DashboardSnapshot(
        generatedAt=generated_at,
        mode=mode,
        brokerMode=broker_mode,
        flow=str(data.get("flow") or "portfolio_review"),
        account=DashboardAccount(
            cash=_number(_first(balance.get("cash"), balance.get("cash_balance"), balance.get("available_cash"))),
            equity=_number(_first(balance.get("equity"), balance.get("portfolio_value"))),
            buyingPower=_number(_first(balance.get("buyingPower"), balance.get("buying_power"))),
            status=str(_first(balance.get("status"), default="ACTIVE" if balance else "UNAVAILABLE")),
            mode=mode,
            lastSyncedAt=generated_at,
        ),
        positions=positions,
        openOrders=public_orders,
        curatorSignals=signals,
        summary=DashboardSummary(
            positionCount=len(positions),
            openOrderCount=len(public_orders),
            curatorSignalCount=len(signals),
            problemCount=problem_count,
            dataSource=data_source,
            serviceStatus="DEGRADED" if degraded else "OK",
            executionStatus=raw_summary.get("execution_status"),
            executionReason=raw_summary.get("execution_reason"),
        ),
    )


def unavailable_dashboard_payload() -> Dict[str, Any]:
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "data_source": "unavailable",
        "balance": {},
        "positions": [],
        "open_orders": [],
        "curator_signals": [],
        "problems": [{}],
        "summary": {"problem_count": 1},
    }
