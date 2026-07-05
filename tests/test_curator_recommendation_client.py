from decimal import Decimal

import pytest

from app import curator_client


@pytest.mark.asyncio
async def test_curator_recommend_skills_posts_context(monkeypatch):
    captured = {}

    async def fake_post(self, path, correlation_id, json_data):
        captured["path"] = path
        captured["json_data"] = json_data
        return {
            "status": "success",
            "data": {"recommendation_state": "ranked", "recommended_skills": []},
        }

    monkeypatch.setattr(curator_client.CuratorAgentClient, "_post", fake_post)

    client = curator_client.CuratorAgentClient()
    result = await client.recommend_skills(
        account_id="1",
        symbol="acgl",
        analysis={"strategy_bucket": "value_rebound", "market_regime": "bullish"},
        correlation_id="cid-1",
    )

    assert result["recommendation_state"] == "ranked"
    assert captured["path"] == "/skills/recommend"
    assert captured["json_data"]["symbol"] == "ACGL"
    assert captured["json_data"]["strategy_bucket"] == "value_rebound"
    assert captured["json_data"]["market_regime"] == "bullish"


@pytest.mark.asyncio
async def test_curator_execute_skill_posts_context_for_database_telemetry(monkeypatch):
    captured = {}

    async def fake_post(self, path, correlation_id, json_data):
        captured["path"] = path
        captured["json_data"] = json_data
        return {"status": "success", "data": {"execution_status": "success"}}

    monkeypatch.setattr(curator_client.CuratorAgentClient, "_post", fake_post)

    client = curator_client.CuratorAgentClient()
    result = await client.execute_skill(
        "skill-1",
        inputs={"analysis": {"score": Decimal("0.5")}},
        correlation_id="cid-1",
        account_id="1",
        symbol="ACGL",
        strategy_bucket="value_rebound",
        market_regime="bullish",
        run_id="cid-1",
    )

    assert result == {"execution_status": "success"}
    assert captured["path"] == "/skills/skill-1/execute"
    assert captured["json_data"]["inputs"] == {"analysis": {"score": 0.5}}
    assert captured["json_data"]["account_id"] == "1"
    assert captured["json_data"]["symbol"] == "ACGL"
    assert captured["json_data"]["strategy_bucket"] == "value_rebound"
    assert captured["json_data"]["market_regime"] == "bullish"
    assert captured["json_data"]["run_id"] == "cid-1"
