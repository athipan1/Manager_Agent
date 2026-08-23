import json
import sys

import pytest

from scripts import run_scanner_preselection as scanner_preselection


def _controlled_no_trade_response():
    return {
        "status": "error",
        "data": {
            "stage": "scanner_discovery",
            "scanner_data": {
                "candidates": [],
                "metadata": {
                    "scanner_opportunity_gate": {
                        "passed_count": 0,
                        "review_count": 10,
                        "controlled_no_trade_count": 10,
                        "workflow_failure_count": 0,
                        "decision": "REVIEW",
                        "review_reason_codes": [
                            "SCANNER_OPPORTUNITY_MARKET_CLOSED"
                        ],
                    }
                },
            },
        },
        "error": {
            "code": "NO_SCANNER_CANDIDATES",
            "message": "Scanner returned zero candidates.",
        },
    }


def test_extract_backtest_symbols_accepts_explicit_controlled_no_trade():
    response = _controlled_no_trade_response()

    assert scanner_preselection._is_controlled_no_trade_response(response) is True
    assert scanner_preselection.extract_backtest_symbols(response) == []


def test_extract_backtest_symbols_still_fails_closed_on_scanner_failure():
    response = _controlled_no_trade_response()
    gate = response["data"]["scanner_data"]["metadata"][
        "scanner_opportunity_gate"
    ]
    gate["workflow_failure_count"] = 1

    assert scanner_preselection._is_controlled_no_trade_response(response) is False
    with pytest.raises(ValueError, match="Scanner preselection failed"):
        scanner_preselection.extract_backtest_symbols(response)


def test_extract_backtest_symbols_requires_positive_controlled_no_trade_count():
    response = _controlled_no_trade_response()
    gate = response["data"]["scanner_data"]["metadata"][
        "scanner_opportunity_gate"
    ]
    gate["controlled_no_trade_count"] = 0

    assert scanner_preselection._is_controlled_no_trade_response(response) is False
    with pytest.raises(ValueError, match="Scanner preselection failed"):
        scanner_preselection.extract_backtest_symbols(response)


def test_main_records_no_trade_as_success(tmp_path, monkeypatch):
    output = tmp_path / "hourly-pre-backtest-discovery.json"
    github_output = tmp_path / "github-output.txt"
    response = _controlled_no_trade_response()

    monkeypatch.setattr(
        scanner_preselection,
        "_request_json",
        lambda *args, **kwargs: (response, 1),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_scanner_preselection.py",
            "--output",
            str(output),
            "--github-output",
            str(github_output),
        ],
    )

    scanner_preselection.main()

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "success"
    assert report["outcome"] == "NO_TRADE"
    assert report["controlled_no_trade"] is True
    assert report["backtest_symbols"] == []

    outputs = github_output.read_text(encoding="utf-8")
    assert "backtest_symbols=" in outputs
    assert "preselection_status=success" in outputs
