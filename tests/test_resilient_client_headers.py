import httpx
import pytest

from app.resilient_client import ResilientAgentClient


@pytest.mark.asyncio
async def test_resilient_client_preserves_api_key_and_adds_correlation_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["api_key"] = request.headers.get("X-API-KEY")
        captured["correlation_id"] = request.headers.get("X-Correlation-ID")
        return httpx.Response(200, json={"status": "success"})

    client = ResilientAgentClient(
        base_url="http://portfolio-agent:8012",
        max_retries=1,
        headers={"X-API-KEY": "portfolio-secret"},
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="http://portfolio-agent:8012",
        headers={"X-API-KEY": "portfolio-secret"},
        transport=httpx.MockTransport(handler),
    )

    try:
        await client._post(
            "/portfolio/exposure",
            "correlation-123",
            {"equity": 100_000, "cash": 100_000, "positions": []},
        )
    finally:
        await client._client.aclose()

    assert captured == {
        "api_key": "portfolio-secret",
        "correlation_id": "correlation-123",
    }
