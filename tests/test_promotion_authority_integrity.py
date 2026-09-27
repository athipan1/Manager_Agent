"""Malformed evidence must never reach approval or the execution candidate set."""
from datetime import timedelta

import pytest

from tests.test_promotion_authority_execution_gate import FakeDatabaseClient, NOW, promotion, run_gate


@pytest.mark.asyncio
@pytest.mark.parametrize("updates,code", [
    ({"version":True},"backtest_promotion_version_invalid"),
    ({"version":0},"backtest_promotion_version_invalid"),
    ({"evidence_version":True},"backtest_promotion_evidence_version_invalid"),
    ({"evidence_version":-1},"backtest_promotion_evidence_version_invalid"),
    ({"updated_at":(NOW+timedelta(hours=1)).isoformat()},"backtest_promotion_timestamp_future"),
    ({"updated_at":"2026-08-03T04:55:00"},"backtest_promotion_timestamp_missing"),
    ({"expires_at":"invalid"},"backtest_promotion_expiration_invalid"),
    ({"expires_at":"2026-08-04T05:00:00"},"backtest_promotion_expiration_invalid"),
    ({"expires_at":"2026-08-04T05:00:00+00:99"},"backtest_promotion_expiration_invalid"),
    ({"expires_at":""},"backtest_promotion_expiration_invalid"),
])
@pytest.mark.parametrize("state",["APPROVED_FOR_PAPER","ROBUSTNESS_PASSED"])
async def test_invalid_authority_blocks_candidates_and_autoapproval(monkeypatch,updates,code,state):
    monkeypatch.setenv("BACKTEST_PROMOTION_APPROVAL_TOKEN","fixture-only-token")
    client=FakeDatabaseClient([promotion(state=state,**updates)])
    result=await run_gate(client,auto_approve=True)
    assert result['selected_positions']==[]
    assert code in result['decisions'][0]['rejection_codes']
    assert client.post_calls==[]


@pytest.mark.asyncio
@pytest.mark.parametrize("updates",[
    {"research_only":True}, {"fixture_only":True}, {"production_authorized":False},
    {"symbol":"OTHER"}, {"strategy_id":"wrong-version"}, {"validation_profile":"wrong"},
    {"updated_at":(NOW-timedelta(days=3)).isoformat()},
])
async def test_preapproval_validates_full_identity_and_provenance(monkeypatch,updates):
    monkeypatch.setenv("BACKTEST_PROMOTION_APPROVAL_TOKEN","fixture-only-token")
    client=FakeDatabaseClient([promotion(state="ROBUSTNESS_PASSED",**updates)])
    result=await run_gate(client,auto_approve=True)
    assert result['summary']['allowed_count']==0
    assert client.post_calls==[]
