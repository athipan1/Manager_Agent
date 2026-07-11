from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import DiscoverAnalyzeTradeRequest
from app.workflows.gated_discovery_workflow import (
    exposure_gate_blocked_execution,
    run_gated_discover_analyze_trade_flow,
)


class FakeScannerClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def discover_best_fundamentals(self, **kwargs):
        return SimpleNamespace(
            data={"candidates": [{"symbol": "AAPL"}]},
            error=None,
        )


class FakeDbClient:
    positions = []
    orders = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_account_balance(self, account_id, correlation_id):
        return SimpleNamespace(cash_balance=Decimal("10000"))

    async def get_positions(self, account_id, correlation_id):
        return list(self.positions)

    async def get_orders(self, account_id, correlation_id):
        return list(self.orders)


def _ranked():
    return [
        {
            "symbol": "AAPL",
            "analysis": {
                "ticker": "AAPL",
                "final_verdict": "buy",
                "status": "complete",
                "raw_data": {},
            },
            "scanner_candidate": {"symbol": "AAPL"},
            "score_breakdown": {"final_opportunity_score": 0.9},
        }
    ]


def _allocation_report():
    position = {
        "symbol": "AAPL",
        "bucket": "value_rebound",
        "strategy_bucket": "value_rebound",
        "target_value": 500.0,
    }
    payload = {
        "ticker": "AAPL",
        "final_verdict": "buy",
        "status": "complete",
        "strategy_bucket": "value_rebound",
        "raw_data": {},
    }
    return {
        "allocation_plan": {"policy_name": "test-policy"},
        "bucket_selection": {},
        "selected_positions": [position],
        "position_analysis_payloads": [payload],
        "ranked_candidates": [{"symbol": "AAPL"}],
        "winner": {"symbol": "AAPL"},
    }


def _patch_common(monkeypatch, *, audits, persisted):
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.ScannerAgentClient",
        FakeScannerClient,
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.DatabaseAgentClient",
        FakeDbClient,
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.select_unique_scanner_tickers",
        lambda candidates: (["AAPL"], {"AAPL": candidates[0]}),
    )

    async def fake_analyze(ticker, correlation_id):
        return _ranked()[0]["analysis"]

    async def fake_context(*args, **kwargs):
        return Decimal("0")

    async def fake_session_context(*args, **kwargs):
        return {"symbol_contexts": {}}

    async def fake_curator(*, payloads, correlation_id):
        return payloads, []

    async def fake_persist(*args, **kwargs):
        persisted.append(kwargs)

    async def fake_audit(*args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.analyze_single_asset",
        fake_analyze,
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.rank_discovery_candidates",
        lambda **kwargs: _ranked(),
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.build_discover_allocation_report",
        lambda **kwargs: _allocation_report(),
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.fetch_context_value",
        fake_context,
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.fetch_session_risk_contexts",
        fake_session_context,
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.enrich_payloads_with_curator_signals",
        fake_curator,
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.persist_signal",
        fake_persist,
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.audit_trade_decision",
        fake_audit,
    )
    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.config_manager.get",
        lambda key, default=None: "acct-1",
    )


def test_exposure_gate_blocked_execution_deduplicates_codes():
    result = exposure_gate_blocked_execution(
        {
            "rejected": [
                {
                    "symbol": "AAPL",
                    "rejection_codes": [
                        "bucket_capacity_exhausted",
                        "existing_positions_not_fully_protected",
                    ],
                },
                {
                    "symbol": "MSFT",
                    "rejection_codes": [
                        "existing_positions_not_fully_protected"
                    ],
                },
            ]
        }
    )

    assert result["status"] == "blocked_by_exposure_gate"
    assert result["rejection_codes"] == [
        "bucket_capacity_exhausted",
        "existing_positions_not_fully_protected",
    ]


@pytest.mark.asyncio
async def test_gated_flow_blocks_risk_when_existing_position_is_unprotected(
    monkeypatch,
):
    FakeDbClient.positions = [
        SimpleNamespace(
            symbol="MSFT",
            quantity=10,
            current_market_price=Decimal("100"),
        )
    ]
    FakeDbClient.orders = []
    audits = []
    persisted = []
    _patch_common(monkeypatch, audits=audits, persisted=persisted)

    def fail_risk(**kwargs):
        raise AssertionError("Risk must not run when exposure gate blocks")

    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.evaluate_portfolio_risk",
        fail_risk,
    )

    response = await run_gated_discover_analyze_trade_flow(
        DiscoverAnalyzeTradeRequest(execute=True),
    )

    assert response.status == "success"
    assert response.data["execution"]["status"] == (
        "blocked_by_exposure_gate"
    )
    assert response.data["selected_positions"] == []
    assert response.data["exposure_gate"]["summary"]["rejected_count"] == 1
    decision = response.data["exposure_gate"]["decisions"][0]
    assert "existing_positions_not_fully_protected" in (
        decision["rejection_codes"]
    )
    assert len(audits) == 1
    assert audits[0]["trade_decision"]["status"] == (
        "blocked_by_exposure_gate"
    )
    assert persisted[0]["extra_metadata"]["exposure_gate_allowed"] is False


@pytest.mark.asyncio
async def test_gated_flow_passes_allowed_candidate_to_portfolio_risk(
    monkeypatch,
):
    FakeDbClient.positions = []
    FakeDbClient.orders = []
    audits = []
    persisted = []
    _patch_common(monkeypatch, audits=audits, persisted=persisted)
    risk_calls = []

    def fake_risk(**kwargs):
        risk_calls.append(kwargs)
        return [
            {
                "approved": False,
                "symbol": "AAPL",
                "reason": "test rejection",
            }
        ]

    monkeypatch.setattr(
        "app.workflows.gated_discovery_workflow.evaluate_portfolio_risk",
        fake_risk,
    )

    response = await run_gated_discover_analyze_trade_flow(
        DiscoverAnalyzeTradeRequest(execute=True),
    )

    assert response.status == "success"
    assert response.data["exposure_gate"]["summary"]["allowed_count"] == 1
    assert response.data["portfolio_summary"]["selected_positions"] == 1
    assert len(risk_calls) == 1
    payload = risk_calls[0]["analysis_results"][0]
    assert payload["exposure_gate"]["allowed"] is True
    assert payload["maximum_order_value"] > 0
    assert response.data["execution"]["status"] == "rejected"
    assert len(audits) == 1
