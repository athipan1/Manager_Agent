from decimal import Decimal
from enum import Enum

import pytest

from app import curator_client


class FakeEnum(Enum):
    BUY = "buy"


class FakeModel:
    def model_dump(self, mode=None):
        return {"nested": {"score": Decimal("0.62")}, "mode": mode or "plain"}


class FakeReportDetails:
    def __init__(self):
        self.summary = "technical report"
        self.score = Decimal("0.63")


@pytest.mark.asyncio
async def test_best_effort_curator_signal_disabled(monkeypatch):
    monkeypatch.setattr(curator_client, "CURATOR_AGENT_ENABLED", False)

    result = await curator_client.best_effort_curator_signal(
        symbol="ACGL",
        analysis={"ticker": "ACGL"},
        correlation_id="cid-1",
    )

    assert result == {"status": "disabled", "reason": "CURATOR_AGENT_ENABLED=false"}


@pytest.mark.asyncio
async def test_best_effort_curator_signal_executes_first_approved_skill(monkeypatch):
    monkeypatch.setattr(curator_client, "CURATOR_AGENT_ENABLED", True)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def search_approved_skills(self, query, correlation_id):
            return [{"skill_id": "skill-1", "name": "RSI Signal"}]

        async def execute_skill(self, skill_id, *, inputs, correlation_id, **kwargs):
            return {
                "execution_status": "success",
                "output": {"signal": "buy", "confidence": 0.7},
                "safety": {"order_placement": False},
            }

    monkeypatch.setattr(curator_client, "CuratorAgentClient", FakeClient)

    result = await curator_client.best_effort_curator_signal(
        symbol="ACGL",
        analysis={"ticker": "ACGL"},
        correlation_id="cid-1",
    )

    assert result["status"] == "success"
    assert result["skill_id"] == "skill-1"
    assert result["skill_name"] == "RSI Signal"
    assert result["execution"]["output"]["signal"] == "buy"


@pytest.mark.asyncio
async def test_best_effort_curator_signal_filters_inputs_by_skill_schema(monkeypatch):
    monkeypatch.setattr(curator_client, "CURATOR_AGENT_ENABLED", True)
    captured = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def search_approved_skills(self, query, correlation_id):
            return [
                {
                    "skill_id": "skill-analysis-only",
                    "name": "Analysis Only Skill",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "analysis": {"type": "object"},
                        },
                    },
                }
            ]

        async def execute_skill(self, skill_id, *, inputs, correlation_id, **kwargs):
            captured["skill_id"] = skill_id
            captured["inputs"] = inputs
            captured["metadata"] = kwargs.get("metadata") or {}
            return {"execution_status": "success", "output": {"signal": "hold"}}

    monkeypatch.setattr(curator_client, "CuratorAgentClient", FakeClient)

    result = await curator_client.best_effort_curator_signal(
        symbol="CINF",
        analysis={"ticker": "CINF", "strategy_bucket": "value_rebound"},
        correlation_id="cid-cinf",
    )

    assert result["status"] == "success"
    assert captured["skill_id"] == "skill-analysis-only"
    assert captured["inputs"] == {"analysis": {"ticker": "CINF", "strategy_bucket": "value_rebound"}}
    assert captured["metadata"]["filtered_input_keys"] == ["analysis"]
    assert captured["metadata"]["dropped_input_keys"] == ["market_regime", "strategy_bucket", "symbol", "ticker"]


@pytest.mark.asyncio
async def test_best_effort_curator_signal_falls_back_to_unavailable(monkeypatch):
    monkeypatch.setattr(curator_client, "CURATOR_AGENT_ENABLED", True)

    class FailingClient:
        async def __aenter__(self):
            raise RuntimeError("curator down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(curator_client, "CuratorAgentClient", FailingClient)

    result = await curator_client.best_effort_curator_signal(
        symbol="ACGL",
        analysis={"ticker": "ACGL"},
        correlation_id="cid-1",
    )

    assert result["status"] == "unavailable"
    assert "curator down" in result["reason"]


def test_json_safe_value_sanitizes_models_and_objects():
    unsafe_payload = {
        "ticker": "ACGL",
        "confidence": Decimal("0.63"),
        "side": FakeEnum.BUY,
        "model": FakeModel(),
        "report_details": FakeReportDetails(),
        "items": {Decimal("1.2"), "x"},
    }

    safe = curator_client.json_safe_value(unsafe_payload)

    assert safe["confidence"] == 0.63
    assert safe["side"] == "buy"
    assert safe["model"]["nested"]["score"] == 0.62
    assert safe["report_details"] == {"summary": "technical report", "score": 0.63}
    assert sorted(safe["items"], key=str) == [1.2, "x"]


def test_filter_skill_inputs_for_schema_keeps_legacy_unspecified_schema():
    inputs = {"symbol": "CINF", "analysis": {}, "strategy_bucket": "value_rebound"}

    assert curator_client.filter_skill_inputs_for_schema({}, inputs) == inputs


def test_filter_skill_inputs_for_schema_drops_undeclared_fields():
    skill = {
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "analysis": {"type": "object"},
            },
        }
    }
    inputs = {
        "symbol": "CINF",
        "analysis": {},
        "ticker": "CINF",
        "strategy_bucket": "value_rebound",
        "market_regime": None,
    }

    assert curator_client.filter_skill_inputs_for_schema(skill, inputs) == {
        "symbol": "CINF",
        "analysis": {},
    }


def test_filter_skill_inputs_uses_manager_advisory_fallback_when_schema_missing():
    skill = {"name": "Manager Advisory Score Signal"}
    inputs = {
        "symbol": "ADBE",
        "analysis": {"ticker": "ADBE"},
        "ticker": "ADBE",
        "strategy_bucket": "value_rebound",
        "market_regime": "risk_on",
    }

    assert curator_client.filter_skill_inputs_for_schema(skill, inputs) == {
        "symbol": "ADBE",
        "analysis": {"ticker": "ADBE"},
        "ticker": "ADBE",
    }


def test_filter_skill_inputs_uses_backtest_fallback_when_schema_missing():
    skill = {"name": "Hourly Backtest Reference Skill"}
    inputs = {
        "symbol": "ACGL",
        "analysis": {"ticker": "ACGL"},
        "ticker": "ACGL",
        "strategy_bucket": "core_dividend",
        "market_regime": "neutral",
    }

    assert curator_client.filter_skill_inputs_for_schema(skill, inputs) == {
        "analysis": {"ticker": "ACGL"},
    }


def test_filter_skill_inputs_uses_backtest_tag_fallback_when_schema_missing():
    skill = {"name": "Any Backtest Skill", "tags": ["hourly", "backtest"]}
    inputs = {
        "symbol": "BKNG",
        "analysis": {"ticker": "BKNG"},
        "ticker": "BKNG",
    }

    assert curator_client.filter_skill_inputs_for_schema(skill, inputs) == {
        "analysis": {"ticker": "BKNG"},
    }


@pytest.mark.asyncio
async def test_curator_execute_skill_sanitizes_inputs_before_post(monkeypatch):
    captured = {}

    async def fake_post(self, path, correlation_id, json_data):
        captured["json_data"] = json_data
        return {"status": "success", "data": {"execution_status": "success"}}

    monkeypatch.setattr(curator_client.CuratorAgentClient, "_post", fake_post)

    client = curator_client.CuratorAgentClient()
    result = await client.execute_skill(
        "skill-1",
        inputs={"analysis": {"details": FakeReportDetails(), "score": Decimal("0.5")}},
        correlation_id="cid-1",
    )

    assert result == {"execution_status": "success"}
    assert captured["json_data"]["inputs"] == {
        "analysis": {"details": {"summary": "technical report", "score": 0.63}, "score": 0.5}
    }
