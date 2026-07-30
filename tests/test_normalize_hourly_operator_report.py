from scripts.normalize_hourly_operator_report import normalize_report


def test_legacy_alpaca_paper_mode_becomes_paper():
    normalized = normalize_report(
        {
            "mode": "ALPACA_PAPER",
            "broker_mode": "ALPACA",
            "runtime": {
                "mode": "ALPACA_PAPER",
                "brokerMode": "ALPACA",
                "dryRun": False,
                "liveTradingEnabled": False,
            },
        }
    )
    assert normalized["mode"] == "PAPER"
    assert normalized["broker_mode"] == "ALPACA"
    assert normalized["runtime"]["mode"] == "PAPER"
    assert normalized["runtime"]["dryRun"] is False
    assert normalized["runtime"]["liveTradingEnabled"] is False


def test_unknown_alpaca_non_dry_run_is_inferred_as_paper():
    normalized = normalize_report(
        {
            "runtime": {
                "mode": "UNKNOWN",
                "brokerMode": "ALPACA",
                "dryRun": False,
                "liveTradingEnabled": True,
            }
        }
    )
    assert normalized["runtime"]["mode"] == "PAPER"
    assert normalized["runtime"]["liveTradingEnabled"] is False


def test_simulator_remains_dry_run_and_live_disabled():
    normalized = normalize_report(
        {
            "mode": "SIMULATOR",
            "broker_mode": "SIMULATOR",
            "runtime": {
                "mode": "SIMULATOR",
                "brokerMode": "SIMULATOR",
                "dryRun": False,
                "liveTradingEnabled": True,
            },
        }
    )
    assert normalized["runtime"]["mode"] == "SIMULATOR"
    assert normalized["runtime"]["dryRun"] is True
    assert normalized["runtime"]["liveTradingEnabled"] is False
