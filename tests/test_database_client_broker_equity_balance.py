from decimal import Decimal

from app.database_client import _broker_account_to_balance


def test_broker_account_to_balance_prefers_equity_when_cash_is_negative():
    balance = _broker_account_to_balance(
        {
            "cash": "-100223.4",
            "buying_power": "3070.74",
            "equity": "101640.32",
            "portfolio_value": "101640.32",
        }
    )

    assert balance.cash_balance == Decimal("101640.32")


def test_broker_account_to_balance_falls_back_to_buying_power_before_cash():
    balance = _broker_account_to_balance(
        {
            "cash": "-100223.4",
            "buying_power": "3070.74",
            "equity": None,
            "portfolio_value": None,
        }
    )

    assert balance.cash_balance == Decimal("3070.74")
