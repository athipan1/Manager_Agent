import pytest

from app import curator_client


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

        async def execute_skill(self, skill_id, *, inputs, correlation_id):
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
