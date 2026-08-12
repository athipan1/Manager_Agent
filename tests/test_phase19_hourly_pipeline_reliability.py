from __future__ import annotations

from pathlib import Path

from scripts.build_hourly_control_artifact import build_control_artifact
from scripts.enrich_decision_analytics import build_analytics


STAGE_ORDER = (
    "scanner",
    "backtest",
    "market_regime",
    "portfolio",
    "profit",
    "risk",
    "execution",
)


def _stages(*, scanner: str = "success") -> list[dict[str, object]]:
    rows = []
    for stage in STAGE_ORDER:
        status = scanner if stage == "scanner" else "not_attempted"
        rows.append(
            {
                "id": stage,
                "status": status,
                "reasonCodes": [],
                "observedAt": "2026-08-10T01:00:00Z",
                "summary": {},
            }
        )
    return rows


def _cycle(
    *,
    source: str,
    reason: str | None,
    cycle_id: str,
    candidates: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "source": source,
        "flowKind": "decision_path",
        "correlationId": cycle_id,
        "cycleId": cycle_id,
        "workflowRunId": 31000000000 + len(cycle_id),
        "observedAt": "2026-08-10T01:00:00Z",
        "status": "controlled_no_trade" if reason else "completed",
        "reasonCode": reason,
        "summary": {},
        "stages": _stages(scanner="skipped" if reason else "success"),
        "candidates": candidates or [],
    }


def _snapshot(cycles: list[dict[str, object]]) -> dict[str, object]:
    current = cycles[0]
    return {
        "schemaVersion": "dashboard-snapshot.v2",
        "generatedAt": "2026-08-10T01:05:00Z",
        "freshness": {
            "isStale": False,
            "ageMinutes": 5,
            "staleAfterMinutes": 120,
        },
        "risk": {"emergencyHalt": {"active": False}},
        "observability": {
            "schemaVersion": "trading-observability.v1",
            "current": current,
            "lastMeaningful": None,
        },
        "decisionHistory": {
            "schemaVersion": "decision-history.v1",
            "generatedAt": "2026-08-10T01:05:00Z",
            "retentionCycles": 24,
            "cycles": cycles,
        },
    }


def test_disabled_schedule_artifact_is_safe_and_broker_inert(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "31360000001")
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "740")
    monkeypatch.setenv("GITHUB_REPOSITORY", "athipan1/Manager_Agent")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Hourly Auto Trading")

    report, supporting = build_control_artifact(observed_at="2026-08-10T05:05:00+00:00")

    assert report["runtime"] == {
        "mode": "PAPER",
        "brokerMode": "ALPACA",
        "dryRun": False,
        "liveTradingEnabled": False,
        "flow": "hourly_portfolio_cycle",
    }
    assert report["cycle"]["status"] == "controlled_no_trade"
    assert report["cycle"]["executionReason"] == "hourly_schedule_disabled"
    assert report["cycle"]["executionAttempted"] is False
    assert report["cycle"]["brokerOrdersSubmitted"] is False
    assert report["positions"] == []
    assert report["openOrders"] == []
    assert report["error"] is None
    assert supporting["marker"]["schemaVersion"] == "hourly-control-cycle.v1"
    assert supporting["marker"]["cycleClass"] == "control"
    assert supporting["marker"]["artifactBacked"] is True
    assert supporting["preflight"]["control_cycle"] is True
    assert supporting["preflight"]["portfolio_cycle_id"] == report["cycle"]["id"]


def test_control_artifact_supports_inactive_soak_reason(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "31360000002")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Alpaca Paper Soak")
    report, supporting = build_control_artifact(
        observed_at="2026-08-10T05:17:00+00:00",
        reason_code="scheduled_paper_cycle_not_authorized",
        market_mode="SOAK_INACTIVE",
        warning="Alpaca Paper soak is inactive.",
    )

    assert report["cycle"]["marketMode"] == "SOAK_INACTIVE"
    assert report["cycle"]["executionReason"] == "scheduled_paper_cycle_not_authorized"
    assert report["cycle"]["executionAttempted"] is False
    assert report["cycle"]["brokerOrdersSubmitted"] is False
    assert supporting["marker"]["cycleClass"] == "control"
    assert supporting["marker"]["reasonCode"] == "scheduled_paper_cycle_not_authorized"


def test_control_cycles_do_not_distort_decision_metrics_or_metadata_gap_count() -> None:
    decision_candidate = {
        "symbol": "AAPL",
        "rank": 1,
        "verdict": "buy",
        "finalScore": 0.8,
        "strategyBucket": "trend",
        "status": "eligible",
        "stageReached": "scanner",
        "reasonCodes": [],
        "refs": {"decisionId": None, "positionId": None},
    }
    cycles = [
        _cycle(
            source="hourly_artifact",
            reason="hourly_schedule_disabled",
            cycle_id="control-new",
        ),
        _cycle(
            source="workflow_metadata",
            reason="scheduled_paper_cycle_not_authorized",
            cycle_id="control-legacy",
        ),
        _cycle(
            source="workflow_metadata",
            reason="hourly_artifact_unavailable",
            cycle_id="real-gap",
        ),
        _cycle(
            source="hourly_artifact",
            reason=None,
            cycle_id="decision-1",
            candidates=[decision_candidate],
        ),
    ]

    analytics = build_analytics(_snapshot(cycles))
    quality = analytics["dataQuality"]

    assert quality["historyCycles"] == 4
    assert quality["meaningfulCycles"] == 1
    assert quality["controlCycles"] == 2
    assert quality["metadataOnlyCycles"] == 1
    assert quality["artifactBackedCycles"] == 2
    assert quality["artifactCoverageRate"] == 0.5
    assert quality["latestCycleClass"] == "control"
    assert analytics["windows"][0]["cyclesAvailable"] == 1
    assert analytics["windows"][0]["metrics"]["candidateCount"] == 1
    assert analytics["windows"][0]["metrics"]["buyCount"] == 1
    alert_codes = {item["code"] for item in analytics["alerts"]}
    assert "consecutive_metadata_only_cycles" not in alert_codes


def test_three_real_metadata_gaps_still_raise_reliability_alert() -> None:
    cycles = [
        _cycle(
            source="workflow_metadata",
            reason="hourly_artifact_unavailable",
            cycle_id=f"gap-{index}",
        )
        for index in range(3)
    ]
    cycles.append(
        _cycle(
            source="hourly_artifact",
            reason=None,
            cycle_id="decision-1",
            candidates=[],
        )
    )

    analytics = build_analytics(_snapshot(cycles))
    alert_codes = {item["code"] for item in analytics["alerts"]}

    assert analytics["dataQuality"]["metadataOnlyCycles"] == 3
    assert "hourly_artifact_unavailable" in alert_codes
    assert "consecutive_metadata_only_cycles" in alert_codes


def test_hourly_workflow_contains_lightweight_disabled_schedule_artifact_job() -> None:
    workflow = Path(".github/workflows/hourly-auto-trading.yml").read_text(encoding="utf-8")

    assert "scheduled-control-cycle:" in workflow
    assert "vars.HOURLY_PAPER_SCHEDULE_ENABLED != 'true'" in workflow
    assert "python scripts/build_hourly_control_artifact.py" in workflow
    assert "name: hourly-auto-trading-report" in workflow
    assert "if-no-files-found: error" in workflow


def test_hourly_workflow_uses_node24_action_releases() -> None:
    workflow = Path(".github/workflows/hourly-auto-trading.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v6" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/upload-artifact@v4" not in workflow


def test_inactive_soak_publishes_authoritative_control_artifact() -> None:
    workflow = Path(".github/workflows/alpaca-paper-soak.yml").read_text(encoding="utf-8")

    assert "inactive-control-artifact:" in workflow
    assert "needs.control.outputs.should_run != 'true'" in workflow
    assert "--market-mode SOAK_INACTIVE" in workflow
    assert "--reason-code scheduled_paper_cycle_not_authorized" in workflow
    assert "name: hourly-auto-trading-report" in workflow
    assert "if-no-files-found: error" in workflow
