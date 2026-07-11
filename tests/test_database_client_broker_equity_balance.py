from decimal import Decimal

from app.database_client import _broker_account_to_balance


def test_broker_account_to_balance_preserves_negative_cash_instead_of_equity():
    balance = _broker_account_to_balance(
        {
            "cash": "-100223.4",
            "buying_power": "3070.74",
            "equity": "101640.32",
            "portfolio_value": "101640.32",
        }
    )

    assert balance.cash_balance == Decimal("-100223.4")


def test_broker_account_to_balance_does_not_treat_buying_power_as_cash():
    balance = _broker_account_to_balance(
        {
            "cash": "-100223.4",
            "buying_power": "3070.74",
            "equity": None,
            "portfolio_value": None,
        }
    )

    assert balance.cash_balance == Decimal("-100223.4")


def test_broker_account_to_balance_uses_equity_only_when_cash_field_is_missing():
    balance = _broker_account_to_balance(
        {
            "buying_power": "3070.74",
            "equity": "101640.32",
            "portfolio_value": "101640.32",
        }
    )

    assert balance.cash_balance == Decimal("101640.32")
