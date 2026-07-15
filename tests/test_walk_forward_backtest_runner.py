from types import SimpleNamespace

from scripts.run_walk_forward_multi_strategy import (
    _deterministic_walk_forward_run_id,
    _walk_forward_metadata,
)


class Dumpable(dict):
    def model_dump(self, mode="json"):
        return dict(self)


def selection(*, passed=True):
    evidence = Dumpable(
        status="completed" if passed else "insufficient_history",
        passed=passed,
        stability_score=0.81,
        evaluated_windows=4 if passed else 2,
        profitable_window_rate=0.75 if passed else 0.0,
        median_sharpe_ratio=0.91 if passed else -0.2,
        median_profit_factor=1.30 if passed else 0.7,
        worst_max_drawdown=-0.08,
        gates={"window_count": passed, "median_sharpe_ratio": passed},
    )
    return SimpleNamespace(
        best_eligible=SimpleNamespace(walk_forward=evidence),
        walk_forward_criteria=Dumpable(min_windows=4),
    )


def test_walk_forward_metadata_preserves_complete_stability_evidence():
    metadata = _walk_forward_metadata(selection())

    assert metadata["validation_profile"] == "rolling_walk_forward_v1"
    assert metadata["walk_forward_required"] is True
    assert metadata["walk_forward_passed"] is True
    assert metadata["walk_forward_evaluated_windows"] == 4
    assert metadata["walk_forward_validation"]["gates"]["window_count"] is True
    assert metadata["walk_forward_criteria"] == {"min_windows": 4}


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
