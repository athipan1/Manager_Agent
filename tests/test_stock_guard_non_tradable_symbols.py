import pytest

from app.stock_guard import StockGuardError, is_stock_symbol, validate_stock_scope


@pytest.mark.parametrize("symbol", ["CASH", "USD", "USDT", "USDC"])
def test_non_tradable_cash_symbols_are_not_stock_symbols(symbol):
    assert is_stock_symbol(symbol) is False
    with pytest.raises(StockGuardError):
        validate_stock_scope(symbol)


def test_real_stock_symbol_still_passes():
    assert is_stock_symbol("ACGL") is True
    validate_stock_scope("ACGL")
