from types import SimpleNamespace

import pytest

from app.services.performance_policy_review_service import (
    curator_payload,
    learning_payload,
    performance_summary_params,
    persist_policy_review_audit,
    persist_policy_review_signal,
    policy_review_audit_payload,
    run_performance_policy_review,
)


class FakeDbClient:
    def __init__(self, fail=False, post_fail=False):
        self.fail = fail
        self.post_fail = post_fail
        self.saved_signals = []
        self.posts = []

    async def save_signal(self, **kwargs):
        if self.fail:
            raise RuntimeError("db unavailable")
        self.saved_signals.append(kwargs)

    async def _post(self, endpoint, correlation_id, json_data=None):
        self.posts.append((endpoint, correlation_id, json_data))
        if self.post_fail:
            raise RuntimeError("policy review endpoint unavailable")
        return {
            "status": "success",
            "data": {
                **(json_data or {}),
                "created_at": "2026-06-28T00:00:00+00:00",
                "updated_at": "2026-06-28T00:00:00+00:00",
            },
        }

    def validate_standard_response(self, response):
        if response.get("status") != "success":
            raise ValueError("non-success response")
        return SimpleNamespace(data=response.get("data"))


def policy_review_payload():
    return {
        "status": "success",
        "advisory_only": True,
        "auto_apply": False,
        "performance_summary": {"closed_plan_count": 10, "net_pnl": 100},
        "learning_result": {"learning_state": "success"},
        "curated_policy": {"curation_state": "review_required", "action_count": 2},
    }


def test_performance_summary_params_filters_symbol_and_account():
    params = performance_summary_params(
        account_id=1,
        symbol="aapl",
        initial_equity=10_000,
        period="30d",
    )

    assert params["account_id"] == "1"
    assert params["symbol"] == "AAPL"
    assert params["initial_equity"] == 10_000
    assert params["period"] == "30d"
    assert params["include_fills"] is True


def test_learning_payload_wraps_performance_summary_and_policy_snapshot(monkeypatch):
    monkeypatch.setattr(
        "app.services.performance_policy_review_service.current_policy_snapshot",
        lambda: {"risk": {"risk_per_trade": 0.01}},
    )
    summary = {"closed_plan_count": 12, "net_pnl": 200}

    payload = learning_payload(account_id="1", performance_summary=summary)

    assert payload["account_id"] == "1"
    assert payload["learning_mode"] == "performance_summary_review"
    assert payload["performance_summary"] == summary
    assert payload["current_policy"]["risk"]["risk_per_trade"] == 0.01
    assert payload["min_closed_plans"] == 5


def test_curator_payload_wraps_learning_result():
    learning_result = {"policy_deltas": {"risk": {"risk_per_trade": -0.0025}}}

    payload = curator_payload(
        account_id=1,
        learning_result=learning_result,
        current_policy={"risk": {"risk_per_trade": 0.01}},
    )

    assert payload["account_id"] == "1"
    assert payload["learning_result"] == learning_result
    assert payload["current_policy"]["risk"]["risk_per_trade"] == 0.01


def test_policy_review_audit_payload_maps_curated_policy_state():
    payload = policy_review_audit_payload(
        account_id="1",
        symbol="aapl",
        correlation_id="corr-1",
        policy_review=policy_review_payload(),
        policy_review_id="review-1",
    )

    assert payload["policy_review_id"] == "review-1"
    assert payload["account_id"] == "1"
    assert payload["symbol"] == "AAPL"
    assert payload["correlation_id"] == "corr-1"
    assert payload["status"] == "review_required"
    assert payload["advisory_only"] is True
    assert payload["auto_apply"] is False
    assert payload["performance_summary"]["net_pnl"] == 100
    assert payload["learning_result"]["learning_state"] == "success"
    assert payload["curated_policy"]["action_count"] == 2
    assert payload["metadata"]["flow"] == "performance_policy_review"


@pytest.mark.asyncio
async def test_persist_policy_review_audit_posts_to_database_endpoint():
    db_client = FakeDbClient()

    record = await persist_policy_review_audit(
        db_client=db_client,
        account_id="1",
        symbol="AAPL",
        correlation_id="corr-1",
        policy_review=policy_review_payload(),
    )

    assert db_client.posts[0][0] == "/policy-reviews"
    assert db_client.posts[0][1] == "corr-1"
    assert db_client.posts[0][2]["status"] == "review_required"
    assert record["policy_review_id"].startswith("policy-review-")
    assert record["auto_apply"] is False


@pytest.mark.asyncio
async def test_persist_policy_review_audit_is_best_effort():
    db_client = FakeDbClient(post_fail=True)

    result = await persist_policy_review_audit(
        db_client=db_client,
        account_id="1",
        symbol="AAPL",
        correlation_id="corr-1",
        policy_review=policy_review_payload(),
    )

    assert result is None


@pytest.mark.asyncio
async def test_persist_policy_review_signal_is_advisory_only():
    db_client = FakeDbClient()
    policy_review = {"status": "success", "curated_policy": {"action_count": 2}}

    await persist_policy_review_signal(
        db_client=db_client,
        account_id="1",
        symbol="AAPL",
        correlation_id="corr-1",
        policy_review=policy_review,
    )

    saved = db_client.saved_signals[0]
    assert saved["final_verdict"] == "policy_review"
    assert saved["metadata"]["advisory_only"] is True
    assert saved["metadata"]["auto_apply"] is False
    assert saved["metadata"]["policy_review"]["status"] == "success"


@pytest.mark.asyncio
async def test_persist_policy_review_signal_is_best_effort():
    db_client = FakeDbClient(fail=True)

    result = await persist_policy_review_signal(
        db_client=db_client,
        account_id="1",
        symbol="AAPL",
        correlation_id="corr-1",
        policy_review={"status": "success"},
    )

    assert result is None


@pytest.mark.asyncio
async def test_run_performance_policy_review_orchestrates_all_steps(monkeypatch):
    async def fake_summary(**kwargs):
        return {"closed_plan_count": 10, "net_pnl": 100}

    async def fake_learning(**kwargs):
        return {"learning_state": "success", "policy_deltas": {"strategy_bucket_weights": {"value_rebound": 0.05}}}

    async def fake_curator(**kwargs):
        return {"curation_state": "review_required", "action_count": 2}

    monkeypatch.setattr("app.services.performance_policy_review_service.config.POLICY_REVIEW_FLOW_ENABLED", True)
    monkeypatch.setattr("app.services.performance_policy_review_service._get_performance_summary", fake_summary)
    monkeypatch.setattr("app.services.performance_policy_review_service._learn_from_summary", fake_learning)
    monkeypatch.setattr("app.services.performance_policy_review_service._curate_learning_result", fake_curator)

    db_client = FakeDbClient()
    result = await run_performance_policy_review(
        db_client=db_client,
        account_id="1",
        symbol="AAPL",
        initial_equity=10_000,
        correlation_id="corr-1",
    )

    assert result["status"] == "success"
    assert result["advisory_only"] is True
    assert result["auto_apply"] is False
    assert result["performance_summary"]["net_pnl"] == 100
    assert result["learning_result"]["learning_state"] == "success"
    assert result["curated_policy"]["action_count"] == 2
    assert result["policy_review_audit_id"].startswith("policy-review-")
    assert db_client.posts[0][0] == "/policy-reviews"
    assert db_client.saved_signals == []


@pytest.mark.asyncio
async def test_run_performance_policy_review_falls_back_to_signal_when_audit_persist_fails(monkeypatch):
    async def fake_summary(**kwargs):
        return {"closed_plan_count": 10, "net_pnl": 100}

    async def fake_learning(**kwargs):
        return {"learning_state": "success"}

    async def fake_curator(**kwargs):
        return {"curation_state": "review_required", "action_count": 2}

    monkeypatch.setattr("app.services.performance_policy_review_service.config.POLICY_REVIEW_FLOW_ENABLED", True)
    monkeypatch.setattr("app.services.performance_policy_review_service._get_performance_summary", fake_summary)
    monkeypatch.setattr("app.services.performance_policy_review_service._learn_from_summary", fake_learning)
    monkeypatch.setattr("app.services.performance_policy_review_service._curate_learning_result", fake_curator)

    db_client = FakeDbClient(post_fail=True)
    result = await run_performance_policy_review(
        db_client=db_client,
        account_id="1",
        symbol="AAPL",
        initial_equity=10_000,
        correlation_id="corr-1",
    )

    assert result["status"] == "success"
    assert "policy_review_audit_id" not in result
    assert db_client.saved_signals[0]["metadata"]["flow"] == "performance_policy_review"


@pytest.mark.asyncio
async def test_run_performance_policy_review_skips_when_disabled(monkeypatch):
    monkeypatch.setattr("app.services.performance_policy_review_service.config.POLICY_REVIEW_FLOW_ENABLED", False)

    result = await run_performance_policy_review(
        db_client=FakeDbClient(),
        account_id="1",
        symbol="AAPL",
        initial_equity=10_000,
        correlation_id="corr-1",
    )

    assert result["status"] == "skipped"
    assert "POLICY_REVIEW_FLOW_ENABLED" in result["reason"]


@pytest.mark.asyncio
async def test_run_performance_policy_review_is_best_effort(monkeypatch):
    async def failing_summary(**kwargs):
        raise RuntimeError("performance unavailable")

    monkeypatch.setattr("app.services.performance_policy_review_service.config.POLICY_REVIEW_FLOW_ENABLED", True)
    monkeypatch.setattr("app.services.performance_policy_review_service._get_performance_summary", failing_summary)

    result = await run_performance_policy_review(
        db_client=FakeDbClient(),
        account_id="1",
        symbol="AAPL",
        initial_equity=10_000,
        correlation_id="corr-1",
    )

    assert result["status"] == "skipped"
    assert result["advisory_only"] is True
    assert result["auto_apply"] is False
    assert "performance unavailable" in result["reason"]
