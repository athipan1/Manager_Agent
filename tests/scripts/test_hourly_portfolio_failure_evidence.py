from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import hourly_portfolio_cycle as cycle


def make_args(tmp_path: Path, phase: str = "prepare") -> argparse.Namespace:
    return argparse.Namespace(
        phase=phase,
        preflight=tmp_path / "hourly-preflight.json",
        review=tmp_path / "hourly-position-review.json",
        manager=tmp_path / "hourly-manager-cycle.json",
        output=tmp_path / "hourly-portfolio-cycle.json",
    )


def test_diagnostic_report_path_matches_phase(tmp_path: Path) -> None:
    assert cycle.diagnostic_report_path(make_args(tmp_path, "prepare")).name == (
        "hourly-position-review.json"
    )
    assert cycle.diagnostic_report_path(make_args(tmp_path, "trade")).name == (
        "hourly-manager-cycle.json"
    )
    assert cycle.diagnostic_report_path(make_args(tmp_path, "finalize")).name == (
        "hourly-portfolio-cycle.json"
    )
    assert cycle.diagnostic_report_path(make_args(tmp_path, "wait")).name == (
        "hourly-portfolio-cycle.json"
    )


def test_persist_failure_report_redacts_secrets_and_keeps_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    args = make_args(tmp_path)
    args.preflight.write_text(
        json.dumps(
            {
                "status": "ready",
                "portfolio_cycle_id": "cycle-123",
                "market_mode": "paper",
                "market_open": True,
                "runtime": {"paper_automation": True},
            }
        ),
        encoding="utf-8",
    )
    secret = "very-secret-token-value"
    monkeypatch.setenv("PORTFOLIO_AGENT_API_KEY", secret)

    try:
        raise RuntimeError(f"Portfolio_Agent failed with {secret}")
    except RuntimeError as exc:
        report_path = cycle.persist_failure_report(args=args, exc=exc)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert payload["schema_version"] == "hourly-portfolio-cycle.failure.v1"
    assert payload["status"] == "failed_closed"
    assert payload["stage"] == "prepare_failed_closed"
    assert payload["preflight"]["portfolio_cycle_id"] == "cycle-123"
    assert payload["preflight"]["paper_automation"] is True
    assert payload["safety"]["execution_continued"] is False
    assert payload["safety"]["broker_mutation_authorized_after_failure"] is False
    assert payload["diagnostics"]["exception_type"] == "RuntimeError"
    assert secret not in serialized
    assert "<redacted:PORTFOLIO_AGENT_API_KEY>" in serialized
    assert "RuntimeError" in payload["diagnostics"]["traceback"]


def test_best_effort_preflight_context_tolerates_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("not-json", encoding="utf-8")

    assert cycle.best_effort_preflight_context(path) == {}
