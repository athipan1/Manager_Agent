import asyncio
from datetime import datetime, timezone

from app.services.backtest_execution_gate import (
    LEGACY_WALK_FORWARD_VALIDATION_PROFILE,
    NESTED_WALK_FORWARD_VALIDATION_PROFILE,
    filter_candidates_with_backtest_gate,
)


NOW = datetime(2026, 8, 2, 15, tzinfo=timezone.utc)
STRATEGY_ID = "trend-following-balanced-v1"


class FakeDatabaseClient:
    def __init__(self, detail):
        self.detail = detail

    async def get_latest_exact_backtest_run(self, **kwargs):
        return self.detail


def nested_metadata(
    *,
    strategy_id=STRATEGY_ID,
    passed=True,
    overlapping=False,
    latest_eligible=True,
    statistical_enabled=True,
    promotion_passed=True,
):
    gates = {
        "window_count": passed,
        "train_eligible_window_rate": passed,
        "profitable_window_rate": passed,
        "median_sharpe_ratio": passed,
        "median_profit_factor": passed,
        "worst_max_drawdown": passed,
        "kill_switch_safety": passed,
    }
    return {
        "validation_profile": NESTED_WALK_FORWARD_VALIDATION_PROFILE,
        "walk_forward_required": True,
        "walk_forward_passed": passed,
        "walk_forward_status": "completed" if passed else "insufficient_history",
        "walk_forward_stability_score": 0.91,
        "selection_method": "nested_train_select_test_evaluate",
        "walk_forward_criteria": {
            "train_bars": 126,
            "test_bars": 126,
            "step_bars": 126,
            "min_windows": 4,
        },
        "walk_forward_validation": {
            "status": "completed" if passed else "insufficient_history",
            "selection_method": "nested_train_select_test_evaluate",
            "passed": passed,
            "evaluated_windows": 4 if passed else 2,
            "overlapping_test_windows": overlapping,
            "latest_selected_strategy_id": strategy_id,
            "latest_selection_eligible": latest_eligible,
            "gates": gates,
        },
        "promotion_gates": {
            "nested_validation_passed": promotion_passed,
            "latest_selection_eligible": promotion_passed,
            "exact_strategy_match": promotion_passed,
            "independent_test_windows": promotion_passed,
            "statistical_validation_enabled": promotion_passed,
        },
        "statistical_criteria": {
            "enabled": statistical_enabled,
            "min_observations": 30,
            "min_trades": 10,
            "max_adjusted_p_value": 0.05,
        },
    }


def detail(metadata, *, strategy_id=STRATEGY_ID):
    return {
        "run": {
            "run_id": "nested-run-1",
            "status": "completed",
            "skill_id": "hourly-sma-crossover",
            "strategy_id": strategy_id,
            "symbol": "AAPL",
            "timeframe": "1d",
            "updated_at": NOW.isoformat(),
            "metadata": metadata,
        },
        "skill_result": {"passed": True},
    }


def evaluate(metadata, *, run_strategy_id=STRATEGY_ID):
    result = asyncio.run(
        filter_candidates_with_backtest_gate(
            db_client=FakeDatabaseClient(
                detail(metadata, strategy_id=run_strategy_id)
            ),
            selected_positions=[{"symbol": "AAPL"}],
            position_analysis_payloads=[{"ticker": "AAPL"}],
            correlation_id="nested-contract-test",
            required=True,
            skill_id="hourly-sma-crossover",
            strategy_id=run_strategy_id,
            strategy_ids=(run_strategy_id,),
            timeframe="1d",
            max_age_hours=26,
            now=NOW,
            walk_forward_required=True,
        )
    )
    return result


def test_nested_profile_allows_complete_independent_statistical_evidence():
    result = evaluate(nested_metadata())

    assert result["summary"] == {
        "candidate_count": 1,
        "allowed_count": 1,
        "rejected_count": 0,
    }
    assert result["validation_profile"] == NESTED_WALK_FORWARD_VALIDATION_PROFILE
    assert result["supported_validation_profiles"] == [
        NESTED_WALK_FORWARD_VALIDATION_PROFILE,
        LEGACY_WALK_FORWARD_VALIDATION_PROFILE,
    ]
    decision = result["decisions"][0]
    assert decision["allowed"] is True
    assert decision["validation_profile"] == NESTED_WALK_FORWARD_VALIDATION_PROFILE
    assert decision["walk_forward_stability_score"] == 0.91
    assert decision["promotion_gates"]["exact_strategy_match"] is True
    assert decision["statistical_criteria"]["enabled"] is True


def test_nested_profile_blocks_overlapping_test_windows():
    result = evaluate(nested_metadata(overlapping=True))

    assert result["summary"]["allowed_count"] == 0
    assert "backtest_nested_test_windows_overlap" in (
        result["rejected"][0]["rejection_codes"]
    )


def test_nested_profile_blocks_latest_strategy_mismatch():
    result = evaluate(
        nested_metadata(strategy_id="mean-reversion-balanced-v1")
    )

    assert "backtest_nested_strategy_mismatch" in (
        result["rejected"][0]["rejection_codes"]
    )


def test_nested_profile_blocks_ineligible_latest_training_selection():
    result = evaluate(nested_metadata(latest_eligible=False))

    assert "backtest_nested_latest_selection_ineligible" in (
        result["rejected"][0]["rejection_codes"]
    )


def test_nested_profile_blocks_missing_or_disabled_statistical_policy():
    missing = nested_metadata()
    missing.pop("statistical_criteria")
    missing_result = evaluate(missing)
    disabled_result = evaluate(
        nested_metadata(statistical_enabled=False)
    )

    assert "backtest_statistical_evidence_missing" in (
        missing_result["rejected"][0]["rejection_codes"]
    )
    assert "backtest_statistical_validation_disabled" in (
        disabled_result["rejected"][0]["rejection_codes"]
    )


def test_nested_profile_blocks_failed_promotion_gates():
    result = evaluate(nested_metadata(promotion_passed=False))

    assert "backtest_nested_promotion_gates_failed" in (
        result["rejected"][0]["rejection_codes"]
    )


def test_nested_profile_blocks_incomplete_history_even_with_run_passed():
    result = evaluate(nested_metadata(passed=False))
    codes = result["rejected"][0]["rejection_codes"]

    assert "backtest_walk_forward_not_passed" in codes
    assert "backtest_walk_forward_incomplete" in codes
    assert "backtest_walk_forward_window_count_invalid" in codes
    assert "backtest_walk_forward_gates_failed" in codes
