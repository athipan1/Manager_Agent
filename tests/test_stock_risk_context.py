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
