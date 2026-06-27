import pytest

from app.alpha_agent_client import build_alpha_advisory


@pytest.mark.asyncio
async def test_build_alpha_advisory_skips_all_when_disabled():
    result = await build_alpha_advisory({}, "test-correlation-id")
    assert result["advisory_only"] is True
    assert result["enabled"] is False
    assert result["results"] == {}
    assert result["errors"] == {}
    assert set(result["skipped"]) == {"market_regime", "portfolio", "profit", "performance"}
