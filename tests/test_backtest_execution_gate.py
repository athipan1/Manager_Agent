import asyncio
from datetime import datetime, timedelta, timezone

from app.services.backtest_execution_gate import (
    filter_candidates_with_backtest_gate,
)


NOW = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)


class FakeDatabaseClient:
    def __init__(self, *, status=None, detail=None, error=None):
        self.status = status or {}
        self.detail = detail or {}
        self.error = error

    async def get_skill_backtest_status(self, skill_id, correlation_id):
        if self.error:
            raise self.error
        return self.status

    async def get_backtest_run(self, run_id, correlation_id):
        return self.detail


def payloads(*symbols):
    positions = [{"symbol": symbol} for symbol in symbols]
    analyses = [{"ticker": symbol} for symbol in symbols]
    return positions, analyses


def evaluate(client, *symbols, required=True):
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
            timeframe="1d",
            max_age_hours=26,
            now=NOW,
        )
    )


def passing_client(*, symbol="AAPL", strategy_id="hourly-sma-crossover"):
    return FakeDatabaseClient(
        status={
            "passed": True,
            "latest_run_id": "run-1",
            "updated_at": NOW.isoformat(),
        },
        detail={
            "run": {
                "run_id": "run-1",
                "status": "completed",
                "skill_id": "hourly-sma-crossover",
                "strategy_id": strategy_id,
                "symbol": symbol,
                "timeframe": "1d",
                "updated_at": NOW.isoformat(),
            }
        },
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


def test_required_gate_accepts_only_exact_latest_passing_run():
    result = evaluate(passing_client(symbol="AAPL"), "AAPL", "MSFT")

    assert [row["symbol"] for row in result["selected_positions"]] == ["AAPL"]
    rejected = result["rejected"][0]
    assert rejected["symbol"] == "MSFT"
    assert "backtest_symbol_mismatch" in rejected["rejection_codes"]


def test_required_gate_blocks_failed_or_missing_result():
    result = evaluate(
        FakeDatabaseClient(status={"passed": False, "latest_run_id": None}),
        "AAPL",
    )

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


def test_required_gate_blocks_stale_result_and_lookup_failure():
    stale = passing_client()
    stale.detail["run"]["updated_at"] = (
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
