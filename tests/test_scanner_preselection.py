import json
import sys

import pytest

from scripts import run_scanner_preselection as scanner_preselection
from scripts.run_scanner_preselection import extract_backtest_symbols


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_extracts_deduplicated_symbols_before_backtest_gate():
    response = {
        "status": "success",
        "data": {
            "pre_backtest_selected_positions": [
                {"symbol": "aapl"},
                {"ticker": "MSFT"},
                {"symbol": "AAPL"},
            ],
            "risk_approvals": [{"symbol": "SHOULD-NOT-BE-USED"}],
        },
    }

    assert extract_backtest_symbols(response) == ["AAPL", "MSFT"]


def test_rejects_failed_manager_response():
    with pytest.raises(ValueError):
        extract_backtest_symbols({"status": "error", "data": {}})


def test_request_retries_transient_timeout_within_deadline(monkeypatch):
    calls = []
    response = {
        "status": "success",
        "data": {"pre_backtest_selected_positions": []},
    }

    def fake_urlopen(request, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        return _FakeResponse(response)

    monkeypatch.setattr(
        scanner_preselection.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(scanner_preselection.time, "sleep", lambda _: None)

    result, attempts = scanner_preselection._request_json(
        "http://manager/discover-analyze-trade",
        {"execute": False},
        attempt_timeout=900,
        deadline_seconds=1200,
        max_attempts=2,
        retry_delay_seconds=0,
    )

    assert result == response
    assert attempts == 2
    assert len(calls) == 2
    assert calls[0] == 900
    assert 1 <= calls[1] <= 900


def test_main_writes_error_diagnostic_before_failing(
    tmp_path,
    monkeypatch,
):
    output = tmp_path / "hourly-pre-backtest-discovery.json"
    github_output = tmp_path / "github-output.txt"
    failure = scanner_preselection.ScannerPreselectionRequestError(
        "Scanner preselection exhausted its bounded request budget",
        attempts_used=2,
        errors=[
            {
                "attempt": 1,
                "timeout_seconds": 900,
                "error_type": "TimeoutError",
                "error": "timed out",
            },
            {
                "attempt": 2,
                "timeout_seconds": 295,
                "error_type": "TimeoutError",
                "error": "timed out",
            },
        ],
    )

    def fail_request(*args, **kwargs):
        raise failure

    monkeypatch.setattr(
        scanner_preselection,
        "_request_json",
        fail_request,
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

    with pytest.raises(SystemExit) as exc_info:
        scanner_preselection.main()

    assert exc_info.value.code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["stage"] == "scanner_preselection"
    assert report["status"] == "error"
    assert report["error_type"] == "ScannerPreselectionRequestError"
    assert report["attempts_used"] == 2
    assert report["request_errors"][0]["error_type"] == "TimeoutError"
    assert report["backtest_symbols"] == []

    outputs = github_output.read_text(encoding="utf-8")
    assert "backtest_symbols=" in outputs
    assert "preselection_status=error" in outputs
    assert f"preselection_report={output}" in outputs


def test_main_writes_success_report_and_outputs(tmp_path, monkeypatch):
    output = tmp_path / "hourly-pre-backtest-discovery.json"
    github_output = tmp_path / "github-output.txt"
    response = {
        "status": "success",
        "data": {
            "pre_backtest_selected_positions": [
                {"symbol": "AAPL"},
                {"symbol": "MSFT"},
            ]
        },
    }

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
    assert report["attempts_used"] == 1
    assert report["backtest_symbols"] == ["AAPL", "MSFT"]

    outputs = github_output.read_text(encoding="utf-8")
    assert "backtest_symbols=AAPL,MSFT" in outputs
    assert "preselection_status=success" in outputs
