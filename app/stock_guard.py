from __future__ import annotations

import re
from typing import Any, Optional

from . import config

_STOCK_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z])?$")
_CRYPTO_HINTS = {"BTC", "ETH", "SOL", "DOGE", "USDT", "USDC", "BNB", "XRP", "ADA"}
_FOREX_HINTS = {"XAU", "XAG", "USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD"}


class StockGuardError(ValueError):
    pass


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def is_stock_symbol(symbol: str) -> bool:
    symbol = normalize_symbol(symbol)
    if not symbol or "/" in symbol or ":" in symbol:
        return False
    if "-" in symbol and not symbol.endswith(('-A', '-B')):
        return False
    if symbol in _CRYPTO_HINTS or symbol.startswith(tuple(_CRYPTO_HINTS)):
        return False
    if symbol in {"XAUUSD", "XAU", "GOLD", "GC"}:
        return False
    return bool(_STOCK_SYMBOL_RE.match(symbol))


def stock_guard_status(symbol: Optional[str] = None) -> dict[str, Any]:
    checks = {
        "asset_class_is_stock": config.ASSET_CLASS == "stock",
        "crypto_disabled": not config.ALLOW_CRYPTO,
        "forex_disabled": not config.ALLOW_FOREX,
        "short_selling_disabled": not config.ALLOW_SHORT_SELLING,
    }
    if symbol:
        checks["symbol_is_stock_like"] = is_stock_symbol(symbol)
    return {
        "approved": all(checks.values()),
        "checks": checks,
        "asset_class": config.ASSET_CLASS,
    }


def validate_stock_scope(symbol: str) -> None:
    if config.ASSET_CLASS != "stock":
        raise StockGuardError(f"Manager is configured for ASSET_CLASS={config.ASSET_CLASS}; stock-first mode requires ASSET_CLASS=stock.")
    if config.ALLOW_CRYPTO or config.ALLOW_FOREX:
        raise StockGuardError("Stock-first mode requires ALLOW_CRYPTO=false and ALLOW_FOREX=false.")
    if not is_stock_symbol(symbol):
        raise StockGuardError(f"Symbol {symbol} is not allowed in stock-first mode.")


def validate_trade_action(symbol: str, action: str, current_position: Any = None) -> None:
    validate_stock_scope(symbol)
    normalized_action = str(action or "hold").lower()
    if normalized_action in {"sell", "strong_sell", "short"}:
        quantity = int(getattr(current_position, "quantity", 0) or 0) if current_position is not None else 0
        if quantity <= 0 and not config.ALLOW_SHORT_SELLING:
            raise StockGuardError(f"Short selling is disabled. Cannot sell {symbol} without an owned long position.")
    if normalized_action in {"short"} and not config.ALLOW_SHORT_SELLING:
        raise StockGuardError("Short selling is disabled in stock-first mode.")
