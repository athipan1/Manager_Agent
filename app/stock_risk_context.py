from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

from . import config


def _as_decimal(value: Any) -> Decimal:
    try:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _position_symbol(position: Any) -> str:
    return str(getattr(position, "symbol", "") or "").upper()


def _position_quantity(position: Any) -> Decimal:
    return _as_decimal(getattr(position, "quantity", 0))


def _position_price(position: Any) -> Decimal:
    return _as_decimal(getattr(position, "current_market_price", None) or getattr(position, "average_cost", None))


def _position_exposure(position: Any) -> Decimal:
    return abs(_position_quantity(position) * _position_price(position))


def _position_sector(position: Any) -> Optional[str]:
    for attr in ("sector", "industry_sector"):
        value = getattr(position, attr, None)
        if value:
            return str(value)
    metadata = getattr(position, "metadata", None)
    if isinstance(metadata, dict):
        value = metadata.get("sector") or metadata.get("industry_sector")
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


def current_sector_exposure(positions: Iterable[Any], sector: Optional[str]) -> Decimal:
    if not sector:
        return Decimal("0")
    sector_norm = str(sector).strip().lower()
    total = Decimal("0")
    for position in positions or []:
        pos_sector = _position_sector(position)
        if pos_sector and pos_sector.strip().lower() == sector_norm:
            total += _position_exposure(position)
    return total


def build_stock_risk_context(symbol: str, positions: Iterable[Any], analysis_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    symbol_upper = str(symbol or "").upper()
    current_position = next((p for p in positions or [] if _position_symbol(p) == symbol_upper), None)
    sector = sector_from_analysis(analysis_result) or _position_sector(current_position)
    return {
        "asset_class": config.ASSET_CLASS,
        "sector": sector,
        "owned_quantity": float(abs(_position_quantity(current_position))) if current_position else 0.0,
        "current_sector_exposure": float(current_sector_exposure(positions or [], sector)),
    }
