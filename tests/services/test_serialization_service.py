import datetime
from decimal import Decimal

from app.services.serialization_service import (
    agent_data,
    as_decimal,
    dict_or_empty,
    jsonable,
    normalize_score,
    response_to_dict,
)


class DummyModel:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, mode="json"):
        return self.payload


def test_response_to_dict_supports_dict_and_model_dump():
    assert response_to_dict({"status": "success"}) == {"status": "success"}
    assert response_to_dict(DummyModel({"status": "ok"})) == {"status": "ok"}
    assert response_to_dict(object()) == {}


def test_normalize_score_clamps_and_handles_percentages():
    assert normalize_score(75) == 0.75
    assert normalize_score("0.42") == 0.42
    assert normalize_score(1.5) == 0.015
    assert normalize_score(-1) == 0.0
    assert normalize_score(200) == 1.0
    assert normalize_score("bad") == 0.0


def test_agent_data_extracts_nested_data():
    assert agent_data({"data": {"action": "buy"}}) == {"action": "buy"}
    assert agent_data({"data": DummyModel({"action": "hold"})}) == {"action": "hold"}
    assert agent_data({"data": []}) == {}


def test_as_decimal_fails_safe():
    assert as_decimal("1.25") == Decimal("1.25")
    assert as_decimal(None) == Decimal("0")
    assert as_decimal({}) == Decimal("0")


def test_jsonable_converts_common_non_json_values():
    timestamp = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)
    payload = {
        "amount": Decimal("1.5"),
        "time": timestamp,
        "nested": [Decimal("2.5"), DummyModel({"ok": True})],
    }

    assert jsonable(payload) == {
        "amount": 1.5,
        "time": timestamp.isoformat(),
        "nested": [2.5, {"ok": True}],
    }


def test_dict_or_empty():
    assert dict_or_empty({"a": 1}) == {"a": 1}
    assert dict_or_empty(None) == {}
    assert dict_or_empty([]) == {}
