from unittest.mock import AsyncMock, patch

import pytest

from app.risk_approval_contract import persist_risk_approval, RiskApprovalContractError


@pytest.mark.asyncio
async def test_persist_risk_approval_posts_database_payload():
    db_client = AsyncMock()
    trade_decision = {
        "approved": True,
        "symbol": "AAPL",
        "action": "buy",
        "position_size": 10,
        "risk_agent_response": {"data": {"approval_id": "risk-from-risk-agent"}},
        "guard_plan": {"symbol": "AAPL", "trigger_price": 90},
        "session_risk_context": {"trades_today": 1},
    }

    approval_id = await persist_risk_approval(
        db_client=db_client,
        trade_decision=trade_decision,
        account_id=1,
        correlation_id="corr-1",
    )

    assert approval_id == "risk-from-risk-agent"
    assert trade_decision["risk_approval_id"] == "risk-from-risk-agent"
    payload = db_client.create_risk_approval.await_args.args[0]
    assert payload["approval_id"] == "risk-from-risk-agent"
    assert payload["account_id"] == 1
    assert payload["symbol"] == "AAPL"
    assert payload["side"] == "buy"
    assert payload["approved_quantity"] == 10
    assert payload["metadata"]["guard_plan"] == {"symbol": "AAPL", "trigger_price": 90}


@pytest.mark.asyncio
async def test_persist_risk_approval_rejects_non_approved_decision():
    db_client = AsyncMock()
    with pytest.raises(RiskApprovalContractError):
        await persist_risk_approval(
            db_client=db_client,
            trade_decision={"approved": False, "symbol": "AAPL", "action": "buy", "position_size": 0},
            account_id=1,
            correlation_id="corr-1",
        )
    db_client.create_risk_approval.assert_not_called()
