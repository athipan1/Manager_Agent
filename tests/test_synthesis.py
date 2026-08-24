from unittest.mock import patch

import pytest

from app.synthesis import get_weighted_verdict


# Format: (tech_action, tech_score, fund_action, fund_score, expected_verdict)
test_data = [
    ("buy", 0.8, "buy", 0.9, "strong_buy"),
    ("sell", 0.8, "sell", 0.9, "strong_sell"),
    ("hold", 0.8, "hold", 0.9, "hold"),
    ("buy", 0.8, "sell", 0.5, "hold"),
    ("buy", 0.5, "sell", 0.8, "hold"),
    ("buy", 0.8, "hold", 0.5, "buy"),
    ("sell", 0.8, "hold", 0.5, "sell"),
]


@pytest.mark.parametrize(
    "tech_action, tech_score, fund_action, fund_score, expected",
    test_data,
)
def test_weighted_verdict_logic_default_weights(
    tech_action,
    tech_score,
    fund_action,
    fund_score,
    expected,
):
    assert (
        get_weighted_verdict(
            tech_action,
            tech_score,
            fund_action,
            fund_score,
            "AAPL",
        )
        == expected
    )


def test_weighted_verdict_logic_dynamic_weights():
    with patch("app.synthesis.config_manager") as mock_config:
        mock_config.get.side_effect = [
            {"technical": 0.8, "fundamental": 0.2},
            {},
        ]
        result = get_weighted_verdict("buy", 0.9, "sell", 0.9, "AAPL")
        assert result == "buy"

        mock_config.get.side_effect = [
            {"technical": 0.8, "fundamental": 0.2},
            {},
        ]
        result = get_weighted_verdict("sell", 0.9, "buy", 0.9, "AAPL")
        assert result == "sell"


def test_weighted_verdict_with_asset_bias():
    with patch("app.synthesis.config_manager") as mock_config:
        mock_config.get.side_effect = [
            {"technical": 0.5, "fundamental": 0.5},
            {"AAPL": 0.7},
        ]
        # Confidence now participates: 1 * .8 * .5 * 1.7 = .68 => BUY.
        result = get_weighted_verdict("buy", 0.8, "hold", 0.5, "AAPL")
        assert result == "buy"

        mock_config.get.side_effect = [
            {"technical": 0.5, "fundamental": 0.5},
            {"MSFT": -0.7},
        ]
        result = get_weighted_verdict("buy", 0.8, "hold", 0.5, "MSFT")
        assert result == "hold"


def test_same_action_has_less_authority_when_confidence_is_low():
    assert get_weighted_verdict("buy", 0.39, "hold", 1.0, "AAPL") == "hold"
    assert get_weighted_verdict("buy", 0.80, "hold", 1.0, "AAPL") == "buy"


def test_strong_buy_requires_strong_confidence_not_just_action_labels():
    assert get_weighted_verdict("buy", 0.79, "buy", 0.79, "AAPL") == "buy"
    assert get_weighted_verdict("buy", 0.80, "buy", 0.80, "AAPL") == "strong_buy"


def test_invalid_confidence_is_fail_safe_neutral():
    assert get_weighted_verdict("buy", float("nan"), "hold", 1.0, "AAPL") == "hold"
    assert get_weighted_verdict("buy", -5, "hold", 1.0, "AAPL") == "hold"
