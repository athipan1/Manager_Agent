from scripts.liquidity_coverage import enrich_hourly_artifact, runtime_report_metadata


def test_paper_mode_with_alpaca_and_dry_run_false_stays_paper():
    metadata = runtime_report_metadata("PAPER", "ALPACA", dry_run=False)

    assert metadata["mode"] == "PAPER"
    assert metadata["broker_mode"] == "ALPACA"
    assert metadata["broker_order_submission_possible"] is True
    assert metadata["warning"].startswith("Alpaca Paper execution mode is active")


def test_paper_mode_dry_run_never_advertises_broker_mutation():
    metadata = runtime_report_metadata("PAPER", "ALPACA", dry_run=True)

    assert metadata["mode"] == "PAPER"
    assert metadata["broker_mode"] == "ALPACA"
    assert metadata["broker_order_submission_possible"] is False
    assert "dry-run" in metadata["warning"]


def test_operator_artifact_enrichment_does_not_rewrite_real_paper_runtime_to_simulator():
    raw = {
        "runtime": {
            "mode": "PAPER",
            "brokerMode": "ALPACA",
            "dryRun": False,
            "liveTradingEnabled": False,
        },
        "mode": "PAPER",
        "broker_mode": "ALPACA",
        "response": {"status": "success", "data": {"ranked_candidates": []}},
    }

    enriched = enrich_hourly_artifact(raw)

    assert enriched["mode"] == "PAPER"
    assert enriched["broker_mode"] == "ALPACA"
    assert enriched["broker_order_submission_possible"] is True
    assert enriched["warning"].startswith("Alpaca Paper execution mode is active")
