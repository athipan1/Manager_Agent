from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import verify_backtest_publish as verifier


def _nested_no_trade_report(*, profile: str = "nested_walk_forward_v3") -> dict:
    return {
        "status": "success",
        "agent_type": "backtest-agent",
        "data": {
            "mode": verifier.NESTED_WALK_FORWARD_MODE,
            "validation_profile": profile,
            "selection_method": verifier.NESTED_SELECTION_METHOD,
            "walk_forward_required": True,
            "no_trade_is_success": True,
            "all_succeeded": True,
            "selection_complete": True,
            "published": True,
            "publish_status": "success",
            "published_count": 0,
            "strategy_ids_by_symbol": {},
            "eligible_symbols": [],
            "ineligible_symbols": ["ALL"],
            "items": [
                {
                    "symbol": "ALL",
                    "status": "no_eligible_strategy",
                    "selected_strategy_id": None,
                    "published": False,
                    "publish_status": "skipped",
                    "database_payload": None,
                    "database_response": None,
                }
            ],
        },
        "error": None,
    }


def test_nested_v3_main_verifies_in_place_without_legacy_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    report_path = tmp_path / "hourly-backtest-result.json"
    payload = _nested_no_trade_report()
    original = json.dumps(payload, indent=2, sort_keys=True)
    report_path.write_text(original, encoding="utf-8")
    (tmp_path / "hourly-backtest-console.json").write_text(
        json.dumps({"event": "backtest_runtime_mode", "backtest_mode": "nested_promotion"})
        + "\n"
        + json.dumps(payload),
        encoding="utf-8",
    )

    def forbidden_legacy_main() -> None:
        raise AssertionError("nested production verification must not run legacy selection")

    monkeypatch.setattr(verifier._legacy, "main", forbidden_legacy_main)
    monkeypatch.setattr(sys, "argv", ["verify_backtest_publish.py", str(report_path)])

    verifier.main()

    assert report_path.read_text(encoding="utf-8") == original
    coherence = json.loads(
        (tmp_path / "hourly-backtest-evidence-coherence.json").read_text(
            encoding="utf-8"
        )
    )
    assert coherence["coherent"] is True
    assert coherence["console_data_sha256"] == coherence["persisted_data_sha256"]
    output = capsys.readouterr().out
    assert "verified in place" in output
    assert "validation_profile=nested_walk_forward_v3" in output
    assert "evidence_coherent=true" in output


def test_nested_v2_is_rejected_in_place_instead_of_falling_back_to_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    report_path = tmp_path / "hourly-backtest-result.json"
    report_path.write_text(
        json.dumps(_nested_no_trade_report(profile="nested_walk_forward_v2")),
        encoding="utf-8",
    )

    legacy_called = False

    def forbidden_legacy_main() -> None:
        nonlocal legacy_called
        legacy_called = True

    monkeypatch.setattr(verifier._legacy, "main", forbidden_legacy_main)
    monkeypatch.setattr(sys, "argv", ["verify_backtest_publish.py", str(report_path)])

    with pytest.raises(SystemExit, match="mode_invalid=True"):
        verifier.main()

    assert legacy_called is False


def test_non_nested_report_preserves_legacy_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    report_path = tmp_path / "legacy.json"
    report_path.write_text(
        json.dumps({"status": "success", "data": {"mode": "legacy_fixed"}}),
        encoding="utf-8",
    )
    called = False

    def fake_legacy_main() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(verifier._legacy, "main", fake_legacy_main)
    monkeypatch.setattr(sys, "argv", ["verify_backtest_publish.py", str(report_path)])

    verifier.main()

    assert called is True
