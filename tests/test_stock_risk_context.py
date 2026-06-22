from decimal import Decimal
from types import SimpleNamespace

from app.stock_risk_context import build_stock_risk_context, current_sector_exposure, sector_from_analysis


def test_sector_from_fundamental_analysis_data():
    result = {
        "raw_data": {
            "fundamental": {
                "data": {
                    "sector": "Technology",
                }
            }
        }
    }
    assert sector_from_analysis(result) == "Technology"


def test_current_sector_exposure_sums_matching_positions():
    positions = [
        SimpleNamespace(symbol="AAPL", quantity=10, average_cost=Decimal("100"), current_market_price=None, metadata={"sector": "Technology"}),
        SimpleNamespace(symbol="MSFT", quantity=5, average_cost=Decimal("200"), current_market_price=None, metadata={"sector": "Technology"}),
        SimpleNamespace(symbol="JNJ", quantity=5, average_cost=Decimal("50"), current_market_price=None, metadata={"sector": "Healthcare"}),
    ]
    assert current_sector_exposure(positions, "Technology") == Decimal("2000")


def test_build_stock_risk_context_includes_owned_quantity_and_sector_exposure():
    positions = [
        SimpleNamespace(symbol="AAPL", quantity=10, average_cost=Decimal("100"), current_market_price=None, metadata={"sector": "Technology"}),
        SimpleNamespace(symbol="MSFT", quantity=5, average_cost=Decimal("200"), current_market_price=None, metadata={"sector": "Technology"}),
    ]
    result = {
        "raw_data": {
            "fundamental": {
                "data": {
                    "sector": "Technology",
                }
            }
        }
    }

    context = build_stock_risk_context("AAPL", positions, result)

    assert context["asset_class"] == "stock"
    assert context["sector"] == "Technology"
    assert context["owned_quantity"] == 10.0
    assert context["current_sector_exposure"] == 2000.0


def test_build_stock_risk_context_supports_broker_dict_positions():
    positions = [
        {"symbol": "AAPL", "qty": "1", "avg_entry_price": "254.48", "current_price": "299.92", "market_value": "299.92", "asset_class": "us_equity"},
        {"symbol": "ACGL", "qty": "2190", "avg_entry_price": "91.31", "current_price": "92.34", "market_value": "202224.6", "asset_class": "us_equity", "metadata": {"sector": "Financial Services"}},
    ]

    context = build_stock_risk_context("ACGL", positions, None)

    assert context["asset_class"] == "stock"
    assert context["sector"] == "Financial Services"
    assert context["owned_quantity"] == 2190.0
    assert context["current_symbol_exposure"] == 202224.6
    assert context["current_sector_exposure"] == 202224.6


def test_build_stock_risk_context_supports_broker_dict_sector_from_analysis():
    positions = [
        {"symbol": "ACGL", "qty": "2190", "current_price": "92.34", "market_value": "202224.6"},
        {"symbol": "AIG", "qty": "100", "current_price": "75", "market_value": "7500", "metadata": {"sector": "Financial Services"}},
    ]
    result = {"raw_data": {"fundamental": {"data": {"sector": "Financial Services"}}}}

    context = build_stock_risk_context("ACGL", positions, result)

    assert context["owned_quantity"] == 2190.0
    assert context["current_symbol_exposure"] == 202224.6
    assert context["current_sector_exposure"] == 209724.6
