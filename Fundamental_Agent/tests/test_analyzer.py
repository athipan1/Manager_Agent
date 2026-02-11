import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.analyzer import (  # noqa: E402
    calculate_growth_score,
    calculate_value_score,
    calculate_dividend_score,
    get_dividend_sustainability_score,
)

# Test Data
sample_data_growth = {
    "Revenue Growth": 0.30,
    "EPS Growth": 0.35,
    "PEG Ratio": 0.8,
    "Forward P/E": 12,
    "ROE": 0.25,
    "Debt to Equity Ratio": 30,
}

sample_data_value = {
    "P/E Ratio": 10,
    "P/B Ratio": 0.8,
    "Debt to Equity Ratio": 40,
    "ROE": 0.18,
    "Profit Margins": 0.22,
    "Operating Cash Flow": 5000000000,
}

sample_data_dividend = {
    "Dividend Yield": 0.05,
    "Dividend History": {
        "2023-12-31": 1.0,
        "2022-12-31": 0.9,
        "2021-12-31": 0.8,
        "2020-12-31": 0.7,
        "2019-12-31": 0.6,
    },
    "Debt to Equity Ratio": 45,
    "Operating Cash Flow": 8000000000,
    "ROE": 0.19,
}


def test_calculate_growth_score():
    """Test the growth scoring logic."""
    trend_score = 0.15  # Assuming 3 years of consistent growth
    scores = calculate_growth_score(sample_data_growth, trend_score)
    assert scores["total"] > 0.7
    assert scores["growth"] > 0.5


def test_calculate_value_score():
    """Test the value scoring logic."""
    scores = calculate_value_score(sample_data_value)
    assert scores["total"] > 0.7
    assert scores["valuation"] > 0.4
    assert scores["financial_health"] > 0.2


def test_calculate_dividend_score():
    """Test the dividend scoring logic."""
    scores = calculate_dividend_score(sample_data_dividend)
    assert scores["total"] > 0.7
    assert scores["yield"] > 0.15
    assert scores["sustainability"] > 0.2


def test_get_dividend_sustainability_score():
    """Test the dividend sustainability logic."""
    score, sustainability = get_dividend_sustainability_score(
        sample_data_dividend["Dividend History"]
    )
    assert score > 0.2
    assert sustainability == "ปันผลเติบโตต่อเนื่อง"
