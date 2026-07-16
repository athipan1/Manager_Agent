from scripts.liquidity_coverage import (
    enrich_hourly_artifact,
    runtime_report_metadata,
    summarize_liquidity_coverage,
)


def _candidate(
    symbol,
    *,
    average_daily_volume=None,
    average_dollar_volume=None,
    spread_bps=None,
    status="partial",
    quote_source="unavailable",
):
    metrics = {}
    if average_daily_volume is not None:
        metrics["average_daily_volume"] = average_daily_volume
    if average_dollar_volume is not None:
        metrics["average_dollar_volume"] = average_dollar_volume
    if spread_bps is not None:
        metrics["spread_bps"] = spread_bps
    return {
        "symbol": symbol,
        "evidence_summary": {
            "technical": {
                "metrics": metrics,
                "provenance": {
                    "liquidity_evidence_version": "liquidity-evidence-v1",
                    "liquidity_evidence_status": status,
                    "liquidity_quote_source": quote_source,
                },
            }
        },
        "investability_gate": {
            "metrics": {
                "average_dollar_volume": average_dollar_volume,
                "spread_bps": spread_bps,
            }
        },
    }


def test_summarize_liquidity_coverage_reports_field_availability():
    summary = summarize_liquidity_coverage(
        [
            _candidate(
                "AAPL",
                average_daily_volume=50_000_000,
                average_dollar_volume=9_000_000_000,
                spread_bps=1.5,
                status="complete",
                quote_source="alpaca_iex",
            ),
            _candidate(
                "BANX",
                average_daily_volume=28_415,
                average_dollar_volume=560_584.65,
            ),
        ]
    )

    assert summary["candidate_count"] == 2
    assert summary["average_daily_volume_available_count"] == 2
    assert summary["average_daily_volume_coverage"] == 1.0
    assert summary["average_daily_volume_coverage_pct"] == 100.0
    assert summary["average_dollar_volume_available_count"] == 2
    assert summary["average_dollar_volume_coverage"] == 1.0
    assert summary["average_dollar_volume_coverage_pct"] == 100.0
    assert summary["spread_available_count"] == 1
    assert summary["spread_coverage"] == 0.5
    assert summary["spread_coverage_pct"] == 50.0
    assert summary["liquidity_evidence_status_counts"] == {
        "complete": 1,
        "partial": 1,
    }
    assert summary["quote_source_counts"] == {
        "alpaca_iex": 1,
        "unavailable": 1,
    }
    assert summary["average_dollar_volume_required_gate_ready"] is True
    assert summary["spread_required_gate_ready"] is False


def test_summarize_liquidity_coverage_rejects_non_finite_values():
    summary = summarize_liquidity_coverage(
        [
            _candidate(
                "BAD",
                average_daily_volume=float("nan"),
                average_dollar_volume=float("inf"),
                spread_bps=-1,
            )
        ]
    )

    assert summary["average_daily_volume_coverage"] == 0.0
    assert summary["average_dollar_volume_coverage"] == 0.0
    assert summary["spread_coverage"] == 0.0
    assert summary["average_dollar_volume_required_gate_ready"] is False
    assert summary["spread_required_gate_ready"] is False


def test_runtime_report_metadata_matches_actual_mode():
    simulator = runtime_report_metadata("SIMULATOR", "SIMULATOR")
    paper = runtime_report_metadata("ALPACA_PAPER", "ALPACA")

    assert simulator["warning"] == (
        "Simulator safety mode is active; no broker orders will be submitted."
    )
    assert simulator["broker_order_submission_possible"] is False
    assert paper["warning"].startswith("Alpaca Paper execution mode is active")
    assert paper["broker_order_submission_possible"] is True


def test_enrich_hourly_artifact_rewrites_warning_and_injects_summary():
    raw = {
        "mode": "SIMULATOR",
        "broker_mode": "SIMULATOR",
        "warning": (
            "DRY_RUN=false with BROKER_MODE=ALPACA sends orders to Alpaca "
            "Paper only."
        ),
        "response": {
            "status": "success",
            "data": {
                "ranked_candidates": [
                    _candidate(
                        "BANX",
                        average_daily_volume=28_415,
                        average_dollar_volume=560_584.65,
                    )
                ]
            },
        },
    }

    enriched = enrich_hourly_artifact(raw)

    assert enriched["warning"] == (
        "Simulator safety mode is active; no broker orders will be submitted."
    )
    assert enriched["broker_order_submission_possible"] is False
    summary = enriched["liquidity_coverage_summary"]
    assert summary["average_dollar_volume_coverage_pct"] == 100.0
    assert summary["spread_coverage_pct"] == 0.0
    assert enriched["response"]["data"][
        "liquidity_coverage_summary"
    ] == summary
