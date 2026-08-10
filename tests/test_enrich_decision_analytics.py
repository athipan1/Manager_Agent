import json

import pytest

from scripts.enrich_decision_analytics import STAGE_ORDER, enrich_snapshot


def candidate(
    symbol: str,
    *,
    verdict: str = "buy",
    status: str = "blocked",
    stage_reached: str = "scanner",
    reasons: list[str] | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "rank": 1,
        "verdict": verdict,
        "finalScore": 0.7,
        "strategyBucket": "value_rebound",
        "status": status,
        "stageReached": stage_reached,
        "reasonCodes": reasons or [],
        "refs": {"decisionId": None, "positionId": None},
    }


def cycle(
    cycle_id: str,
    *,
    source: str = "hourly_artifact",
    candidates: list[dict] | None = None,
    backtest_status: str = "success",
    risk_status: str = "success",
    execution_status: str = "success",
    reason_code: str | None = None,
) -> dict:
    rows = candidates or []
    stages = []
    for stage_id in STAGE_ORDER:
        status = "success"
        if stage_id == "backtest":
            status = backtest_status
        elif stage_id == "risk":
            status = risk_status
        elif stage_id == "execution":
            status = execution_status
        stages.append(
            {
                "id": stage_id,
                "status": status,
                "reasonCodes": [],
                "observedAt": "2026-08-09T14:00:00Z",
                "summary": {},
            }
        )
    blocked = [item for item in rows if item["status"] == "blocked"]
    return {
        "source": source,
        "flowKind": "decision_path",
        "correlationId": f"corr-{cycle_id}" if source == "hourly_artifact" else None,
        "cycleId": cycle_id if source == "hourly_artifact" else None,
        "workflowRunId": abs(hash(cycle_id)) % 1_000_000 + 1,
        "observedAt": "2026-08-09T14:00:00Z",
        "status": "controlled_no_trade",
        "reasonCode": reason_code,
        "summary": {
            "candidateCount": len(rows),
            "buyCount": sum(item["verdict"] == "buy" for item in rows),
            "blockedCount": len(blocked),
            "executedCount": sum(item["status"] == "executed" for item in rows),
            "riskRejectedCount": sum(item["stageReached"] == "risk" and item["status"] == "blocked" for item in rows),
            "executionFailureCount": sum(item["stageReached"] == "execution" and item["status"] in {"blocked", "failure"} for item in rows),
        },
        "stages": stages,
        "candidates": rows,
    }


def snapshot(cycles: list[dict], *, stale: bool = False, emergency_halt: bool = False) -> dict:
    current = cycles[0]
    meaningful = next((item for item in cycles if item["source"] == "hourly_artifact"), current)
    return {
        "schemaVersion": "dashboard-snapshot.v2",
        "generatedAt": "2026-08-09T14:05:00Z",
        "freshness": {"ageMinutes": 10, "isStale": stale, "staleAfterMinutes": 120},
        "risk": {
            "emergencyHalt": {
                "active": emergency_halt,
                "updatedAt": "2026-08-09T14:04:00Z",
            }
        },
        "observability": {
            "schemaVersion": "trading-observability.v1",
            "current": current,
            "lastMeaningful": meaningful,
        },
        "decisionHistory": {
            "schemaVersion": "decision-history.v1",
            "generatedAt": "2026-08-09T14:05:00Z",
            "retentionCycles": 24,
            "cycles": cycles,
        },
    }


def alert_codes(analytics: dict) -> set[str]:
    return {item["code"] for item in analytics["alerts"]}


def test_computes_window_rates_funnel_and_top_blocking_reasons():
    rows = [
        candidate("AAA", status="executed", stage_reached="execution"),
        candidate("BBB", status="blocked", stage_reached="risk", reasons=["risk_rejected"]),
        candidate(
            "CCC",
            verdict="hold",
            status="blocked",
            stage_reached="scanner",
            reasons=["investability_market_cap_below_minimum"],
        ),
    ]
    analytics = enrich_snapshot(snapshot([cycle("one", candidates=rows)]))["decisionAnalytics"]
    window = analytics["windows"][0]

    assert analytics["schemaVersion"] == "decision-analytics.v1"
    assert [item["size"] for item in analytics["windows"]] == [6, 12, 24]
    assert window["cyclesAvailable"] == 1
    assert window["metrics"] == {
        "candidateCount": 3,
        "buyCount": 2,
        "blockedCount": 2,
        "executedCount": 1,
        "riskRejectedCount": 1,
        "executionFailureCount": 0,
    }
    assert window["rates"]["blockedRate"] == pytest.approx(2 / 3, rel=1e-5)
    assert window["rates"]["executionRate"] == pytest.approx(1 / 3, rel=1e-5)
    assert window["rates"]["riskRejectionRate"] == 0.5
    funnel = {item["stage"]: item for item in window["funnel"]}
    assert funnel["scanner"]["reachedCount"] == 3
    assert funnel["backtest"]["reachedCount"] == 2
    assert funnel["risk"]["reachedCount"] == 2
    assert funnel["execution"]["reachedCount"] == 1
    assert {item["code"] for item in window["topBlockingReasons"]} == {
        "risk_rejected",
        "investability_market_cap_below_minimum",
    }


def test_excludes_metadata_cycles_from_trading_metrics_and_alerts_data_quality():
    metadata = [
        cycle(
            f"meta-{index}",
            source="workflow_metadata",
            reason_code="hourly_artifact_unavailable",
            backtest_status="skipped",
            risk_status="not_attempted",
            execution_status="not_attempted",
        )
        for index in range(3)
    ]
    meaningful = cycle(
        "meaningful",
        candidates=[candidate("AAA")],
        backtest_status="skipped",
        risk_status="not_attempted",
        execution_status="not_attempted",
    )
    analytics = enrich_snapshot(snapshot([*metadata, meaningful]))["decisionAnalytics"]

    assert analytics["windows"][0]["cyclesAvailable"] == 1
    assert analytics["windows"][0]["metrics"]["candidateCount"] == 1
    assert analytics["dataQuality"] == {
        "historyCycles": 4,
        "meaningfulCycles": 1,
        "controlCycles": 0,
        "metadataOnlyCycles": 3,
        "artifactBackedCycles": 1,
        "artifactCoverageRate": 0.25,
        "latestCycleSource": "workflow_metadata",
        "latestCycleClass": "metadata_gap",
        "latestReasonCode": "hourly_artifact_unavailable",
        "latestMeaningfulObservedAt": "2026-08-09T14:00:00Z",
        "sufficientFor6CycleWindow": False,
        "sufficientForTrendComparison": False,
    }
    assert {
        "hourly_artifact_unavailable",
        "consecutive_metadata_only_cycles",
        "insufficient_meaningful_history",
    }.issubset(alert_codes(analytics))
    assert analytics["overallStatus"] == "warning"


def test_raises_critical_alerts_for_emergency_halt_and_execution_failure():
    failed = candidate(
        "FAIL",
        status="failure",
        stage_reached="execution",
        reasons=["execution_failed"],
    )
    analytics = enrich_snapshot(
        snapshot([cycle("failed", candidates=[failed])], stale=True, emergency_halt=True)
    )["decisionAnalytics"]

    assert analytics["overallStatus"] == "critical"
    assert {
        "emergency_halt_active",
        "snapshot_stale",
        "recent_execution_failure",
    }.issubset(alert_codes(analytics))


def test_detects_consecutive_backtest_and_risk_non_progress():
    cycles = [
        cycle(
            f"cycle-{index}",
            candidates=[candidate(f"SYM{index}")],
            backtest_status="skipped",
            risk_status="not_attempted",
            execution_status="not_attempted",
        )
        for index in range(3)
    ]
    analytics = enrich_snapshot(snapshot(cycles))["decisionAnalytics"]

    assert "consecutive_no_backtest_progress" in alert_codes(analytics)
    assert "consecutive_risk_not_attempted" in alert_codes(analytics)


def test_detects_high_risk_rejection_rate_only_after_risk_has_sample_size():
    rejected = [
        candidate(f"R{index}", status="blocked", stage_reached="risk", reasons=["risk_rejected"])
        for index in range(4)
    ]
    analytics = enrich_snapshot(snapshot([cycle("risk", candidates=rejected)]))["decisionAnalytics"]

    assert analytics["windows"][0]["rates"]["riskRejectionRate"] == 1.0
    assert "high_risk_rejection_rate" in alert_codes(analytics)


def test_compares_latest_six_with_previous_six_when_history_is_sufficient():
    latest = [
        cycle(
            f"latest-{index}",
            candidates=[candidate(f"L{index}", status="blocked", stage_reached="scanner")],
        )
        for index in range(6)
    ]
    previous = [
        cycle(
            f"previous-{index}",
            candidates=[candidate(f"P{index}", status="executed", stage_reached="execution")],
        )
        for index in range(6)
    ]
    analytics = enrich_snapshot(snapshot([*latest, *previous]))["decisionAnalytics"]

    assert analytics["trend"] == {
        "comparison": "latest6_vs_previous6",
        "enoughData": True,
        "latestCycles": 6,
        "previousCycles": 6,
        "candidateCountDelta": 0,
        "blockedRateDeltaPoints": 100.0,
        "executionRateDeltaPoints": -100.0,
        "riskRejectionRateDeltaPoints": None,
    }


def test_fails_closed_for_wrong_history_or_incomplete_cycle():
    payload = snapshot([cycle("one")])
    payload["decisionHistory"]["schemaVersion"] = "decision-history.v0"
    with pytest.raises(ValueError, match="decision-history.v1"):
        enrich_snapshot(payload)

    payload = snapshot([cycle("one")])
    payload["decisionHistory"]["cycles"][0]["stages"] = payload["decisionHistory"]["cycles"][0]["stages"][:-1]
    with pytest.raises(ValueError, match="seven-stage"):
        enrich_snapshot(payload)


def test_does_not_propagate_sensitive_reason_values():
    unsafe = candidate(
        "SAFE",
        status="blocked",
        stage_reached="scanner",
        reasons=["password=hunter2", "api_key=never-copy"],
    )
    analytics = enrich_snapshot(snapshot([cycle("safe", candidates=[unsafe])]))["decisionAnalytics"]
    serialized = json.dumps(analytics).lower()

    assert "hunter2" not in serialized
    assert "never-copy" not in serialized
    assert analytics["windows"][0]["topBlockingReasons"] == []
