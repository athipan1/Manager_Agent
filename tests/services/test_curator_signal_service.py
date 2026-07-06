import pytest

from app.services import curator_signal_service


@pytest.mark.asyncio
async def test_enrich_payloads_with_curator_signals_attaches_metadata(monkeypatch):
    async def fake_best_effort_curator_signal(*, symbol, analysis, correlation_id):
        return {
            "status": "success",
            "skill_id": "skill-1",
            "execution": {
                "execution_status": "success",
                "output": {"signal": "buy", "confidence": 0.7, "reason": "test"},
            },
        }

    monkeypatch.setattr(
        curator_signal_service,
        "best_effort_curator_signal",
        fake_best_effort_curator_signal,
    )

    payloads = [{"ticker": "ACGL", "metadata": {"existing": True}}]

    enriched, signals = await curator_signal_service.enrich_payloads_with_curator_signals(
        payloads=payloads,
        correlation_id="cid-1",
    )

    assert enriched[0]["metadata"]["existing"] is True
    assert enriched[0]["metadata"]["curator_signal"]["status"] == "success"
    assert enriched[0]["metadata"]["curator_account_id"] == "1"
    assert signals == [
        {
            "symbol": "ACGL",
            "account_id": "1",
            "status": "success",
            "skill_id": "skill-1",
            "execution": {
                "execution_status": "success",
                "output": {"signal": "buy", "confidence": 0.7, "reason": "test"},
            },
        }
    ]


@pytest.mark.asyncio
async def test_enrich_payloads_with_curator_signals_preserves_payload_without_symbol(monkeypatch):
    called = False

    async def fake_best_effort_curator_signal(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "success"}

    monkeypatch.setattr(
        curator_signal_service,
        "best_effort_curator_signal",
        fake_best_effort_curator_signal,
    )

    payloads = [{"name": "missing-symbol"}]

    enriched, signals = await curator_signal_service.enrich_payloads_with_curator_signals(
        payloads=payloads,
        correlation_id="cid-1",
    )

    assert enriched == payloads
    assert signals == []
    assert called is False
