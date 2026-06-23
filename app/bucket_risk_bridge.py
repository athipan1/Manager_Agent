from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional

from .discover_allocation import BUCKET_PRIORITY, select_candidates_by_bucket
from .stock_risk_context import build_stock_risk_context


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _position_symbol(position: Any) -> str:
    return str(getattr(position, "symbol", "") or "").upper()


def _position_quantity(position: Any) -> int:
    try:
        return int(getattr(position, "quantity", 0) or 0)
    except Exception:
        return 0


def _position_exposure(position: Any) -> Decimal:
    if position is None:
        return Decimal("0")
    qty = abs(_decimal(getattr(position, "quantity", 0)))
    price = _decimal(getattr(position, "current_market_price", None) or getattr(position, "average_cost", None))
    return qty * price


def _total_position_exposure(positions: List[Any]) -> Decimal:
    return sum((_position_exposure(position) for position in positions or []), Decimal("0"))


def extract_entry_price(analysis: Mapping[str, Any]) -> Decimal:
    raw = analysis.get("raw_data") or {}
    technical = raw.get("technical") or {}
    data = technical.get("data") or {}
    return _decimal(data.get("current_price") or analysis.get("current_price"))


def extract_technical_stop(analysis: Mapping[str, Any]) -> Optional[Decimal]:
    raw = analysis.get("raw_data") or {}
    technical = raw.get("technical") or {}
    data = technical.get("data") or {}
    indicators = data.get("indicators") or {}
    value = indicators.get("stop_loss") or analysis.get("technical_stop_loss")
    stop = _decimal(value)
    return stop if stop > 0 else None


def _ranked_by_symbol(ranked: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(item.get("symbol") or "").upper(): item for item in ranked or [] if item.get("symbol")}


def build_bucket_risk_decisions(
    *,
    ranked: List[Dict[str, Any]],
    portfolio_value: Decimal,
    positions: List[Any],
    open_orders_exposure: Decimal,
    session_context: Dict[str, Any],
    min_final_score: float,
    assess_trade_fn: Callable[..., Dict[str, Any]],
    risk_per_trade: Decimal,
    fixed_stop_loss_pct: Decimal,
    enable_technical_stop: bool,
    max_position_pct: Decimal,
    margin_multiplier: Decimal,
    max_checks: int = 5,
) -> Dict[str, Any]:
    """Run Risk_Agent checks for the selected candidates in each bucket.

    This helper is intentionally order-safe: it only calls the risk check function
    and returns decisions. It does not submit orders.
    """
    selection = select_candidates_by_bucket(ranked, min_final_score=min_final_score)
    source = _ranked_by_symbol(ranked)
    decisions: Dict[str, Any] = {}
    checked = 0
    total_exposure = _total_position_exposure(positions)

    for bucket in BUCKET_PRIORITY:
        bucket_rows = (selection.get(bucket) or {}).get("selected") or []
        bucket_decisions = []
        for row in bucket_rows:
            if checked >= max_checks:
                bucket_decisions.append({
                    "symbol": row.get("symbol"),
                    "strategy_bucket": bucket,
                    "approved": False,
                    "status": "skipped",
                    "reason": "max risk checks reached",
                })
                continue
            symbol = str(row.get("symbol") or "").upper()
            item = source.get(symbol)
            analysis = (item or {}).get("analysis") or {}
            final_verdict = analysis.get("final_verdict") or row.get("final_verdict") or "hold"
            entry_price = extract_entry_price(analysis)
            if entry_price <= 0:
                bucket_decisions.append({
                    "symbol": symbol,
                    "strategy_bucket": bucket,
                    "approved": False,
                    "status": "not_attempted",
                    "reason": "missing entry price for risk check",
                })
                continue
            current_position = next((position for position in positions or [] if _position_symbol(position) == symbol), None)
            stock_context = build_stock_risk_context(symbol, positions or [], analysis)
            stock_context["strategy_bucket"] = bucket
            decision = assess_trade_fn(
                portfolio_value=Decimal(portfolio_value),
                risk_per_trade=risk_per_trade,
                fixed_stop_loss_pct=fixed_stop_loss_pct,
                enable_technical_stop=enable_technical_stop,
                max_position_pct=max_position_pct,
                symbol=symbol,
                action=final_verdict,
                entry_price=entry_price,
                technical_stop_loss=extract_technical_stop(analysis),
                current_position_size=_position_quantity(current_position),
                current_symbol_exposure=_position_exposure(current_position),
                current_total_exposure=total_exposure,
                open_orders_exposure=open_orders_exposure,
                margin_multiplier=margin_multiplier,
                session_risk_context=session_context,
                stock_risk_context=stock_context,
            )
            decision["strategy_bucket"] = bucket
            bucket_decisions.append(decision)
            checked += 1
        decisions[bucket] = bucket_decisions

    return {
        "bucket_selection": selection,
        "bucket_risk_decisions": decisions,
        "summary": {
            "risk_checks_attempted": checked,
            "max_checks": max_checks,
            "approved_count": sum(1 for bucket in BUCKET_PRIORITY for decision in decisions.get(bucket, []) if decision.get("approved")),
        },
    }
