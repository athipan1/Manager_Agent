from unittest.mock import patch

import pytest

from app.stock_guard import StockGuardError, is_stock_symbol, validate_trade_action


class Position:
    quantity = 3


def test_stock_symbol_allows_common_us_tickers():
    assert is_stock_symbol("AAPL") is True
    assert is_stock_symbol("MSFT") is True
    assert is_stock_symbol("BRK.B") is True


def test_stock_symbol_blocks_crypto_forex_and_gold():
    assert is_stock_symbol("BTCUSD") is False
    assert is_stock_symbol("XAUUSD") is False
    assert is_stock_symbol("EUR/USD") is False


def test_long_only_blocks_sell_without_position():
    with patch("app.stock_guard.config.ASSET_CLASS", "stock"), \
            patch("app.stock_guard.config.ALLOW_CRYPTO", False), \
            patch("app.stock_guard.config.ALLOW_FOREX", False), \
            patch("app.stock_guard.config.ALLOW_SHORT_SELLING", False):
        with pytest.raises(StockGuardError):
            validate_trade_action("AAPL", "sell", None)


def test_long_only_allows_sell_owned_position():
    with patch("app.stock_guard.config.ASSET_CLASS", "stock"), \
            patch("app.stock_guard.config.ALLOW_CRYPTO", False), \
            patch("app.stock_guard.config.ALLOW_FOREX", False), \
            patch("app.stock_guard.config.ALLOW_SHORT_SELLING", False):
        validate_trade_action("AAPL", "sell", Position())
