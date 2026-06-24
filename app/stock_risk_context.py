from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

from . import config
from .portfolio_allocation import UNASSIGNED, classify_strategy_bucket


def _get(position: Any, *names: str, default: Any = None) -> Any:
    if position is None:
        return default
    if isinstance(position, dict):
        for name in names:
            value = position.get(name)
            if value is not None:
                return value
        return default
    for name in names:
        value = getattr(position, name, None)
        if value is not None:
            return value
    return default


def _as_decimal(value: Any) -> Decimal:
    try:
        if value is None or value == "":
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _position_symbol(position: Any) -> str:
    return str(_get(position, "symbol", default="") or "").upper()


def _position_quantity(position: Any) -> Decimal:
    return _as_decimal(_get(position, "quantity", "qty", "owned_quantity", default=0))


def _position_price(position: Any) -> Decimal:
    return _as_decimal(_get(position, "current_market_price", "current_price", "market_price", "average_cost", "avg_entry_price", default=0))


def _position_market_value(position: Any) -> Decimal:
    market_value = _as_decimal(_get(position, "market_value", "value", default=None))
    if market_value:
        return abs(market_value)
    return abs(_position_quantity(position) * _position_price(position))


def _position_exposure(position: Any) -> Decimal:
    return _position_market_value(position)


def _position_sector(position: Any) -> Optional[str]:
    for attr in ("sector", "industry_sector"):
        value = _get(position, attr, default=None)
        if value:
            return str(value)
    metadata = _get(position, "metadata", default=None)
    if isinstance(metadata, dict):
        value = metadata.get("sector") or metadata.get("industry_sector")
        if value:
            return str(value)
    return None


def _position_strategy_bucket(position: Any) -> Optional[str]:
    for attr in ("strategy_bucket", "bucket", "allocation_bucket"):
        value = _get(position, attr, default=None)
        if value:
            return str(value)
    metadata = _get(position, "metadata", default=None)
    if isinstance(metadata, dict):
        value = metadata.get("strategy_bucket") or metadata.get("bucket") or metadata.get("allocation_bucket")
        if value:
            return str(value)
    return None


def _agent_data(result: Dict[str, Any], agent_name: str) -> Dict[str, Any]:
    raw = (result.get("raw_data") or {}).get(agent_name) or {}
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="json")
    data = (raw or {}).get("data") or {}
    return data if isinstance(data, dict) else {}


def sector_from_analysis(result: Optional[Dict[str, Any]]) -> Optional[str]:
    if not result:
        return None
    for source in (_agent_data(result, "fundamental"), _agent_data(result, "technical")):
        sector = source.get("sector") or source.get("industry_sector")
        if sector:
            return str(sector)
    scanner = result.get("scanner_candidate") or {}
    if isinstance(scanner, dict):
        metadata = scanner.get("metadata") or {}
        sector = scanner.get("sector") or metadata.get("sector")
        if sector:
            return str(sector)
    return None


def strategy_bucket_from_analysis(result: Optional[Dict[str, Any]], current_position: Any = None) -> str:
    if result:
        explicit_bucket = result.get("strategy_bucket") or (result.get("portfolio_context") or {}).get("strategy_bucket") or (result.get("portfolio_context") or {}).get("bucket")
        if explicit_bucket:
            return str(explicit_bucket)
        try:
            return classify_strategy_bucket({"analysis": result, "scanner_candidate": result.get("scanner_candidate"), "score_breakdown": result.get("score_breakdown") or {}})
        except Exception:
            pass
    return _position_strategy_bucket(current_position) or UNASSIGNED


def current_sector_exposure(positions: Iterable[Any], sector: Optional[str], *, inferred_symbol: Optional[str] = None) -> Decimal:
    if not sector:
        return Decimal("0")
    sector_norm = str(sector).strip().lower()
    inferred_symbol_upper = str(inferred_symbol or "").upper()
    total = Decimal("0")
    for position in positions or []:
        pos_sector = _position_sector(position)
        if pos_sector and pos_sector.strip().lower() == sector_norm:
            total += _position_exposure(position)
        elif inferred_symbol_upper and _position_symbol(position) == inferred_symbol_upper:
            total += _position_exposure(position)
    return total


def current_bucket_exposure(positions: Iterable[Any], strategy_bucket: str, *, inferred_symbol: Optional[str] = None) -> Decimal:
    if not strategy_bucket or strategy_bucket == UNASSIGNED:
        return Decimal("0")
    bucket_norm = str(strategy_bucket).strip().lower()
    inferred_symbol_upper = str(inferred_symbol or "").upper()
    total = Decimal("0")
    for position in positions or []:
        pos_bucket = _position_strategy_bucket(position)
        if pos_bucket and pos_bucket.strip().lower() == bucket_norm:
            total += _position_exposure(position)
        elif inferred_symbol_upper and _position_symbol(position) == inferred_symbol_upper:
            total += _position_exposure(position)
    return total


def build_stock_risk_context(symbol: str, positions: Iterable[Any], analysis_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    symbol_upper = str(symbol or "").upper()
    current_position = next((p for p in positions or [] if _position_symbol(p) == symbol_upper), None)
    analysis_result = analysis_result or {}
    portfolio_context = analysis_result.get("portfolio_context") or {}
    sector = sector_from_analysis(analysis_result) or _position_sector(current_position)
    strategy_bucket = strategy_bucket_from_analysis(analysis_result, current_position)
    context = {
        "asset_class": config.ASSET_CLASS,
        "sector": sector,
        "strategy_bucket": strategy_bucket,
        "owned_quantity": float(abs(_position_quantity(current_position))) if current_position else 0.0,
        "current_symbol_exposure": float(_position_exposure(current_position)) if current_position else 0.0,
        "current_sector_exposure": float(current_sector_exposure(positions or [], sector, inferred_symbol=symbol_upper)),
        "current_bucket_exposure": float(current_bucket_exposure(positions or [], strategy_bucket, inferred_symbol=symbol_upper)),
    }
    for key in ("target_weight", "allocation_pct", "target_value", "suggested_max_value", "suggested_equal_weight_value"):
        if key in portfolio_context and portfolio_context.get(key) is not None:
            context[key] = portfolio_context.get(key)
    return context
