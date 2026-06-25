from decimal import Decimal

from app.services.exposure_service import position_exposure, total_position_exposure


class Position:
    def __init__(self, quantity, current_market_price=None, average_cost=None):
        self.quantity = quantity
        self.current_market_price = current_market_price
        self.average_cost = average_cost


def test_position_exposure_uses_current_market_price_first():
    position = Position(quantity="3", current_market_price="10", average_cost="8")

    assert position_exposure(position) == Decimal("30")


def test_position_exposure_falls_back_to_average_cost():
    position = Position(quantity="3", average_cost="8")

    assert position_exposure(position) == Decimal("24")


def test_position_exposure_is_absolute_and_fails_safe():
    short_position = Position(quantity="-2", current_market_price="11")
    bad_position = Position(quantity="bad", current_market_price="11")

    assert position_exposure(short_position) == Decimal("22")
    assert position_exposure(bad_position) == Decimal("0")
    assert position_exposure(None) == Decimal("0")


def test_total_position_exposure_sums_positions():
    positions = [
        Position(quantity="1", current_market_price="10"),
        Position(quantity="2", current_market_price="20"),
    ]

    assert total_position_exposure(positions) == Decimal("50")
