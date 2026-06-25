import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import config
from app.services.audit_service import audit_trade_decision, dry_run_report, persist_signal


class FakeDbClient:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.saved = []

    async def save_signal(self, **kwargs):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.saved.append(kwargs)


def test_dry_run_report_builds_legacy_payload(monkeypatch):
    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")
    monkeypatch.setattr(config, "TRADING_ENABLED", True)
    generated_at = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)

    report = dry_run_report(
        correlation_id="cid",
        flow="analyze",
        symbol="AAPL",
        analysis_result={"final_verdict": "buy"},
        trade_decision={
            "risk_approval_id": "risk-1",
            "session_risk_context": {"trades_today": 1},
        },
        execution_result={"status": "dry_run"},
        context_value=Decimal("12.5"),
        dry_run=True,
        generated_at=generated_at,
    )

    assert report == {
        "report_id": "cid",
        "flow": "analyze",
        "symbol": "AAPL",
        "dry_run": True,
        "trading_mode": "PAPER",
        "trading_enabled": True,
        "risk_context": {
            "open_orders_exposure": 12.5,
            "session": {"trades_today": 1},
            "loaded": True,
        },
        "analysis": {"final_verdict": "buy"},
        "trade_decision": {
            "risk_approval_id": "risk-1",
            "session_risk_context": {"trades_today": 1},
        },
        "risk_approval_id": "risk-1",
        "execution": {"status": "dry_run"},
        "generated_at": generated_at.isoformat(),
    }


@pytest.mark.asyncio
async def test_audit_trade_decision_persists_audit_metadata():
    db_client = FakeDbClient()

    audit = await audit_trade_decision(
        db_client=db_client,
        account_id=1,
        correlation_id="cid",
        flow="analyze",
        symbol="AAPL",
        analysis_result={"final_verdict": "buy"},
        trade_decision={"risk_approval_id": "risk-1"},
        execution_result={"status": "submitted"},
        context_value=Decimal("0"),
        dry_run=False,
    )

    assert audit["risk_approval_id"] == "risk-1"
    assert db_client.saved == [
        {
            "account_id": 1,
            "symbol": "AAPL",
            "correlation_id": "cid",
            "final_verdict": "buy",
            "metadata": {
                "audit": audit,
                "risk_approval_id": "risk-1",
                "dry_run": False,
                "flow": "analyze",
            },
        }
    ]


@pytest.mark.asyncio
async def test_audit_trade_decision_does_not_raise_on_persist_failure():
    db_client = FakeDbClient(fail=True)

    audit = await audit_trade_decision(
        db_client=db_client,
        account_id=1,
        correlation_id="cid",
        flow="analyze",
        symbol="AAPL",
        analysis_result={"final_verdict": "hold"},
        trade_decision=None,
        execution_result={"status": "not_attempted"},
        context_value=Decimal("0"),
    )

    assert audit["final_verdict"] if "final_verdict" in audit else audit["analysis"]["final_verdict"] == "hold"


@pytest.mark.asyncio
async def test_persist_signal_saves_scores_and_metadata():
    db_client = FakeDbClient()
    details = SimpleNamespace(
        technical=SimpleNamespace(score=0.7, action="buy"),
        fundamental=SimpleNamespace(score=0.8, action="hold"),
    )

    await persist_signal(
        db_client=db_client,
        account_id=1,
        analysis_result={
            "ticker": "AAPL",
            "status": "complete",
            "final_verdict": "buy",
            "details": details,
        },
        correlation_id="cid",
        extra_metadata={"flow": "unit"},
    )

    assert db_client.saved == [
        {
            "account_id": 1,
            "symbol": "AAPL",
            "correlation_id": "cid",
            "technical_score": 0.7,
            "fundamental_score": 0.8,
            "final_verdict": "buy",
            "metadata": {
                "analysis_status": "complete",
                "technical_action": "buy",
                "fundamental_action": "hold",
                "flow": "unit",
            },
        }
    ]


@pytest.mark.asyncio
async def test_persist_signal_does_not_raise_on_failure():
    db_client = FakeDbClient(fail=True)

    await persist_signal(
        db_client=db_client,
        account_id=1,
        analysis_result={"ticker": "AAPL"},
        correlation_id="cid",
    )
