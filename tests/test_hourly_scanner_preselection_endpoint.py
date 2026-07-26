from datetime import datetime, timezone
import inspect

import pytest
from fastapi import HTTPException

from app.contracts import StandardAgentResponse
from app.models import DiscoverAnalyzeTradeRequest
from app.routes import discovery
from app.workflows import scanner_preselection_workflow
from app.workflows.scanner_preselection_workflow import (
    _mark_verified_snapshot_context,
    run_scanner_preselection_flow,
)
from scripts.run_scanner_preselection import _payload_from_env


def _success_response(flow: str) -> StandardAgentResponse:
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc),
        data={"flow": flow, "pre_backtest_selected_positions": []},
    )


def test_hourly_payload_carries_cycle_identity(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_CYCLE_ID", "hourly-paper-cycle-1")
    monkeypatch.setenv("MAX_UNIVERSE", "500")
    monkeypatch.setenv("TOP_N", "7")
    monkeypatch.setenv("MIN_FINAL_SCORE", "0.61")

    payload = _payload_from_env()

    assert payload["execute"] is False
    assert payload["portfolio_cycle_id"] == "hourly-paper-cycle-1"
    assert payload["max_universe"] == 500
    assert payload["top_n"] == 7
    assert payload["min_final_score"] == 0.61


@pytest.mark.asyncio
async def test_scanner_preselection_route_uses_read_only_workflow(monkeypatch):
    calls = []

    async def fake_preselection(request):
        calls.append(request)
        return _success_response("scanner_preselection")

    monkeypatch.setattr(
        discovery,
        "run_scanner_preselection_flow",
        fake_preselection,
    )

    request = DiscoverAnalyzeTradeRequest(
        account_id=1,
        execute=False,
        portfolio_cycle_id="hourly-paper-cycle-1",
    )
    response = await discovery.scanner_preselection_endpoint(request)

    assert response.data["flow"] == "scanner_preselection"
    assert calls == [request]


@pytest.mark.asyncio
async def test_scanner_preselection_refuses_execution_requests():
    request = DiscoverAnalyzeTradeRequest(account_id=1, execute=True)

    with pytest.raises(HTTPException) as exc_info:
        await run_scanner_preselection_flow(request)

    assert exc_info.value.status_code == 400
    assert "execute=false" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_unsynced_database_blocks_before_scanner(monkeypatch):
    scanner_created = False

    async def fake_sync_status(account_id, correlation_id):
        return {
            "mismatch": {
                "summary": {
                    "status": "mismatch",
                    "recommended_action": "refresh_broker_sync",
                }
            }
        }

    class UnexpectedScannerClient:
        def __init__(self):
            nonlocal scanner_created
            scanner_created = True

    monkeypatch.setattr(
        scanner_preselection_workflow,
        "load_database_sync_status",
        fake_sync_status,
    )
    monkeypatch.setattr(
        scanner_preselection_workflow,
        "ScannerAgentClient",
        UnexpectedScannerClient,
    )

    request = DiscoverAnalyzeTradeRequest(
        account_id=1,
        execute=False,
        portfolio_cycle_id="hourly-paper-cycle-2",
    )
    with pytest.raises(HTTPException) as exc_info:
        await run_scanner_preselection_flow(request)

    assert exc_info.value.status_code == 503
    assert "verified Database/Alpaca snapshot" in str(exc_info.value.detail)
    assert scanner_created is False


def test_verified_snapshot_marker_is_scoped_to_client_instance():
    first = type(
        "FakeDatabaseClient",
        (),
        {"_broker_context_reconciled_accounts": set()},
    )()
    second = type(
        "FakeDatabaseClient",
        (),
        {"_broker_context_reconciled_accounts": set()},
    )()

    _mark_verified_snapshot_context(first, 1)

    assert first._broker_context_reconciled_accounts == {"1"}
    assert second._broker_context_reconciled_accounts == set()


def test_read_only_workflow_has_no_execution_agent_client_dependency():
    source = inspect.getsource(scanner_preselection_workflow)

    assert "ExecutionAgentClient" not in source
    assert "execute_portfolio_batch" not in source
