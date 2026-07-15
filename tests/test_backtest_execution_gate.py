import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.backtest_execution_gate import (
    filter_candidates_with_backtest_gate,
)


NOW = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)


class FakeDatabaseClient:
    def __init__(self, *, details=None, error=None):
        self.details = details or {}
        self.error = error
        self.calls = []

    async def get_latest_exact_backtest_run(
        self,
        *,
        skill_id,
        strategy_id,
        symbol,
        timeframe,
        correlation_id,
    ):
        self.calls.append((skill_id, strategy_id, symbol, timeframe))
        if self.error:
            raise self.error
        return self.details.get(
            (symbol, strategy_id),
            self.details.get(symbol, {}),
        )


def payloads(*symbols):
    positions = [{"symbol": symbol} for symbol in symbols]
    analyses = [{"ticker": symbol} for symbol in symbols]
    return positions, analyses


def evaluate(
    client,
    *symbols,
    required=True,
    strategy_ids=(),
    walk_forward_required=False,
):
    positions, analyses = payloads(*symbols)
    return asyncio.run(
        filter_candidates_with_backtest_gate(
            db_client=client,
            selected_positions=positions,
            position_analysis_payloads=analyses,
            correlation_id="test-correlation",
            required=required,
            skill_id="hourly-sma-crossover",
            strategy_id="hourly-sma-crossover",
            strategy_ids=strategy_ids,
            timeframe="1d",
            max_age_hours=26,
            now=NOW,
            walk_forward_required=walk_forward_required,
        )
    )


def walk_forward_metadata(*, passed=True, status="completed", windows=4):
    gates = {
        "window_count": windows >= 4,
        "profitable_window_rate": passed,
        "median_sharpe_ratio": passed,
        "median_profit_factor": passed,
        "worst_max_drawdown": passed,
        "kill_switch_safety": passed,
    }
    return {
        "validation_profile": "rolling_walk_forward_v1",
        "walk_forward_required": True,
        "walk_forward_passed": passed,
        "walk_forward_status": status,
        "walk_forward_stability_score": 0.82,
        "walk_forward_criteria": {"min_windows": 4},
        "walk_forward_validation": {
            "status": status,
            "passed": passed,
            "evaluated_windows": windows,
            "gates": gates,
        },
        "selection_gates": {
            "full_period_trade_count": True,
            "full_period_sharpe_ratio": True,
            "walk_forward_window_count": windows >= 4,
            "walk_forward_profitable_window_rate": passed,
        },
    }


def passing_detail(
    *,
    symbol="AAPL",
    strategy_id="hourly-sma-crossover",
    updated_at=None,
    metadata=None,
):
    return {
        "run": {
            "run_id": f"run-{symbol.lower()}-{strategy_id}",
            "status": "completed",
            "skill_id": "hourly-sma-crossover",
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": "1d",
            "updated_at": updated_at or NOW.isoformat(),
            "metadata": metadata or {},
        },
        "skill_result": {"passed": True},
    }


def passing_client(*, symbol="AAPL", strategy_id="hourly-sma-crossover"):
    return FakeDatabaseClient(
        details={
            symbol: passing_detail(
                symbol=symbol,
                strategy_id=strategy_id,
            )
        }
    )


def test_disabled_gate_preserves_all_candidates_without_database_evidence():
    result = evaluate(
        FakeDatabaseClient(error=RuntimeError("unused")),
        "AAPL",
        "MSFT",
        required=False,
    )

    assert result["status"] == "disabled"
    assert result["summary"] == {
        "candidate_count": 2,
        "allowed_count": 2,
        "rejected_count": 0,
    }


def test_required_gate_accepts_each_independent_exact_latest_passing_run():
    client = passing_client(symbol="AAPL")
    client.details.update(passing_client(symbol="MSFT").details)
    result = evaluate(client, "AAPL", "MSFT")

    assert [row["symbol"] for row in result["selected_positions"]] == [
        "AAPL",
        "MSFT",
    ]
    assert result["rejected"] == []
    assert client.calls == [
        ("hourly-sma-crossover", "hourly-sma-crossover", "AAPL", "1d"),
        ("hourly-sma-crossover", "hourly-sma-crossover", "MSFT", "1d"),
    ]


def test_required_gate_blocks_failed_or_missing_result():
    result = evaluate(FakeDatabaseClient(), "AAPL")

    assert result["summary"]["allowed_count"] == 0
    assert result["rejected"][0]["rejection_codes"] == [
        "backtest_not_found",
        "backtest_not_passed",
    ]


def test_required_gate_blocks_strategy_mismatch():
    result = evaluate(
        passing_client(strategy_id="different-strategy"),
        "AAPL",
    )

    assert result["summary"]["allowed_count"] == 0
    assert (
        "backtest_strategy_mismatch"
        in result["rejected"][0]["rejection_codes"]
    )


def test_required_gate_blocks_cross_symbol_evidence():
    client = passing_client(symbol="AAPL")
    client.details["MSFT"] = client.details.pop("AAPL")

    result = evaluate(client, "MSFT")

    assert result["summary"]["allowed_count"] == 0
    assert (
        "backtest_symbol_mismatch"
        in result["rejected"][0]["rejection_codes"]
    )


def test_required_gate_blocks_stale_result_and_lookup_failure():
    stale = passing_client()
    stale.details["AAPL"]["run"]["updated_at"] = (
        NOW - timedelta(hours=27)
    ).isoformat()
    stale_result = evaluate(stale, "AAPL")
    failed_result = evaluate(
        FakeDatabaseClient(error=RuntimeError("database unavailable")),
        "AAPL",
    )

    assert "backtest_stale" in stale_result["rejected"][0]["rejection_codes"]
    assert (
        "backtest_lookup_failed"
        in failed_result["rejected"][0]["rejection_codes"]
    )
    assert failed_result["summary"]["allowed_count"] == 0


def test_not_found_http_error_is_not_reported_as_database_failure():
    error = RuntimeError("404 Not Found")
    error.response = SimpleNamespace(status_code=404)

    result = evaluate(FakeDatabaseClient(error=error), "AAPL")

    codes = result["rejected"][0]["rejection_codes"]
    assert "backtest_not_found" in codes
    assert "backtest_lookup_failed" not in codes
    assert result["lookup_errors"] == {}


def test_multi_strategy_gate_selects_newest_exact_passing_strategy():
    older = (NOW - timedelta(hours=2)).isoformat()
    newer = (NOW - timedelta(minutes=10)).isoformat()
    client = FakeDatabaseClient(
        details={
            ("AAPL", "trend-following-balanced-v1"): passing_detail(
                symbol="AAPL",
                strategy_id="trend-following-balanced-v1",
                updated_at=older,
            ),
            ("AAPL", "mean-reversion-balanced-v1"): passing_detail(
                symbol="AAPL",
                strategy_id="mean-reversion-balanced-v1",
                updated_at=newer,
            ),
        }
    )

    result = evaluate(
        client,
        "AAPL",
        strategy_ids=(
            "trend-following-balanced-v1",
            "mean-reversion-balanced-v1",
        ),
    )

    assert result["summary"]["allowed_count"] == 1
    assert result["strategy_ids_by_symbol"] == {
        "AAPL": "mean-reversion-balanced-v1"
    }


def test_multi_strategy_gate_never_falls_back_to_legacy_strategy():
    client = passing_client(strategy_id="hourly-sma-crossover")

    result = evaluate(
        client,
        "AAPL",
        strategy_ids=(
            "sma-crossover-balanced-v1",
            "trend-following-balanced-v1",
        ),
    )

    assert result["summary"]["allowed_count"] == 0
    assert result["strategy_ids_by_symbol"] == {}
    assert all(
        call[1] != "hourly-sma-crossover" for call in client.calls
    )


def test_walk_forward_gate_accepts_complete_persisted_evidence():
    strategy_id = "trend-following-balanced-v1"
    client = FakeDatabaseClient(
        details={
            ("AAPL", strategy_id): passing_detail(
                symbol="AAPL",
                strategy_id=strategy_id,
                metadata=walk_forward_metadata(),
            )
        }
    )

    result = evaluate(
        client,
        "AAPL",
        strategy_ids=(strategy_id,),
        walk_forward_required=True,
    )

    assert result["summary"]["allowed_count"] == 1
    assert result["walk_forward_required"] is True
    decision = result["decisions"][0]
    assert decision["walk_forward_passed"] is True
    assert decision["walk_forward_stability_score"] == 0.82


def test_walk_forward_gate_blocks_legacy_full_period_record():
    strategy_id = "trend-following-balanced-v1"
    client = FakeDatabaseClient(
        details={
            ("AAPL", strategy_id): passing_detail(
                symbol="AAPL",
                strategy_id=strategy_id,
            )
        }
    )

    result = evaluate(
        client,
        "AAPL",
        strategy_ids=(strategy_id,),
        walk_forward_required=True,
    )

    codes = result["rejected"][0]["rejection_codes"]
    assert "backtest_walk_forward_evidence_missing" in codes
    assert "backtest_walk_forward_not_passed" in codes
    assert result["summary"]["allowed_count"] == 0


def test_walk_forward_gate_blocks_incomplete_or_failed_validation():
    strategy_id = "mean-reversion-balanced-v1"
    client = FakeDatabaseClient(
        details={
            ("AAPL", strategy_id): passing_detail(
                symbol="AAPL",
                strategy_id=strategy_id,
                metadata=walk_forward_metadata(
                    passed=False,
                    status="insufficient_history",
                    windows=2,
                ),
            )
        }
    )

    result = evaluate(
        client,
        "AAPL",
        strategy_ids=(strategy_id,),
        walk_forward_required=True,
    )

    codes = result["rejected"][0]["rejection_codes"]
    assert "backtest_walk_forward_not_passed" in codes
    assert "backtest_walk_forward_incomplete" in codes
    assert "backtest_walk_forward_gates_failed" in codes
    assert "backtest_walk_forward_window_count_invalid" in codes
