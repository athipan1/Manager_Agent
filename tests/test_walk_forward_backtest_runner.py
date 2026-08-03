from types import SimpleNamespace

from scripts.run_walk_forward_multi_strategy import (
    _deterministic_walk_forward_run_id,
    _walk_forward_metadata,
)


class Dumpable(dict):
    def model_dump(self, mode="json"):
        return dict(self)


def selection(*, passed=True):
    strategy_id = "trend-following-balanced-v1"
    evidence = Dumpable(
        status="completed" if passed else "insufficient_history",
        selection_method="nested_train_select_test_evaluate",
        passed=passed,
        stability_score=0.81,
        evaluated_windows=4 if passed else 2,
        train_eligible_window_rate=0.75 if passed else 0.0,
        profitable_window_rate=0.75 if passed else 0.0,
        median_sharpe_ratio=0.91 if passed else -0.2,
        median_profit_factor=1.30 if passed else 0.7,
        worst_max_drawdown=-0.08,
        overlapping_test_windows=False,
        latest_selected_strategy_id=strategy_id,
        latest_selection_eligible=passed,
        gates={"window_count": passed, "median_sharpe_ratio": passed},
    )
    return SimpleNamespace(
        best_eligible=SimpleNamespace(strategy_id=strategy_id),
        nested_walk_forward=evidence,
        walk_forward_criteria=Dumpable(min_windows=4),
    )


def test_walk_forward_metadata_preserves_complete_stability_evidence():
    metadata = _walk_forward_metadata(selection())

    assert metadata["validation_profile"] == "nested_walk_forward_v2"
    assert metadata["selection_method"] == "nested_train_select_test_evaluate"
    assert metadata["walk_forward_required"] is True
    assert metadata["walk_forward_passed"] is True
    assert metadata["walk_forward_evaluated_windows"] == 4
    assert metadata["walk_forward_train_eligible_window_rate"] == 0.75
    assert metadata["walk_forward_validation"]["gates"]["window_count"] is True
    assert metadata["walk_forward_criteria"] == {"min_windows": 4}
    assert all(metadata["promotion_gates"].values())
    assert metadata["statistical_criteria"]["enabled"] is True


def test_walk_forward_run_identity_changes_with_stability_thresholds():
    common = {
        "symbol": "AAPL",
        "strategy_id": "trend-following-balanced-v1",
        "fingerprint": "dataset-1",
        "parameters": {"fast_window": 20, "slow_window": 50},
        "timeframe": "1d",
        "engine_version": "backtest-agent-0.6.0",
    }

    first = _deterministic_walk_forward_run_id(
        walk_forward_criteria={"min_windows": 4},
        **common,
    )
    stricter = _deterministic_walk_forward_run_id(
        walk_forward_criteria={"min_windows": 5},
        **common,
    )

    assert first != stricter
