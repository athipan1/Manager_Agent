import json
from pathlib import Path

import pytest

from scripts.enrich_decision_history import MAX_CYCLES, STAGE_ORDER, enrich_snapshot


def cycle(
    cycle_id: str,
    *,
    observed_at: str = "2026-08-09T14:00:00Z",
    symbol: str = "BANX",
    status: str = "blocked",
    stage_reached: str = "scanner",
) -> dict:
    return {
        "source": "hourly_artifact",
        "flowKind": "decision_path",
        "correlationId": f"corr-{cycle_id}",
        "cycleId": cycle_id,
        "workflowRunId": 100,
        "observedAt": observed_at,
        "status": "controlled_no_trade",
        "reasonCode": "market_closed",
        "stages": [
            {
                "id": stage_id,
                "status": "success" if stage_id == "scanner" else "not_attempted",
                "reasonCodes": [],
                "observedAt": observed_at,
                "summary": {},
            }
            for stage_id in STAGE_ORDER
        ],
        "candidates": [
            {
                "symbol": symbol,
                "rank": 1,
                "verdict": "buy",
                "finalScore": 0.638,
                "strategyBucket": "value_rebound",
                "status": status,
                "stageReached": stage_reached,
                "reasonCodes": ["investability_market_cap_below_minimum"],
            }
        ],
    }


def snapshot(current: dict, last_meaningful: dict | None = None) -> dict:
    return {
        "schemaVersion": "dashboard-snapshot.v2",
        "generatedAt": "2026-08-09T14:05:00Z",
        "observability": {
            "schemaVersion": "trading-observability.v1",
            "current": current,
            "lastMeaningful": last_meaningful or current,
        },
    }


def test_accumulates_deduplicates_and_bounds_history():
    current = cycle("cycle-new")
    previous_cycles = [
        cycle(f"cycle-{index}", observed_at=f"2026-08-08T{index % 24:02d}:00:00Z")
        for index in range(30)
    ]
    previous = {
        "decisionHistory": {
            "schemaVersion": "decision-history.v1",
            "cycles": [current, *previous_cycles],
        }
    }

    history = enrich_snapshot(snapshot(current), previous)["decisionHistory"]

    assert history["schemaVersion"] == "decision-history.v1"
    assert history["retentionCycles"] == MAX_CYCLES
    assert len(history["cycles"]) == MAX_CYCLES
    assert history["cycles"][0]["cycleId"] == "cycle-new"
    assert len({item["cycleId"] for item in history["cycles"]}) == MAX_CYCLES


def test_seeds_from_previous_phase16_observability_when_history_is_absent():
    current = cycle("cycle-current")
    previous_cycle = cycle("cycle-previous", observed_at="2026-08-09T13:00:00Z")
    previous = {
        "observability": {
            "schemaVersion": "trading-observability.v1",
            "current": previous_cycle,
            "lastMeaningful": previous_cycle,
        }
    }

    cycles = enrich_snapshot(snapshot(current), previous)["decisionHistory"]["cycles"]

    assert [item["cycleId"] for item in cycles] == ["cycle-current", "cycle-previous"]


def test_adds_safe_candidate_refs_and_never_copies_raw_diagnostics(tmp_path: Path):
    current = cycle("cycle-ref", symbol="AAPL", status="blocked", stage_reached="risk")
    discovery = {
        "response": {
            "data": {
                "ranked_candidates": [
                    {
                        "symbol": "AAPL",
                        "decision_id": "decision-safe-1",
                        "position_id": "position-safe-1",
                        "diagnostics": {"api_key": "never-copy-me"},
                    }
                ],
                "risk_approvals": [
                    {
                        "symbol": "AAPL",
                        "decision_id": "decision-safe-1",
                        "position_id": "position-safe-1",
                        "client_order_id": "never-public",
                    }
                ],
            }
        }
    }
    (tmp_path / "hourly-pre-backtest-discovery.json").write_text(
        json.dumps(discovery), encoding="utf-8"
    )

    history = enrich_snapshot(snapshot(current), artifact_dir=tmp_path)["decisionHistory"]
    candidate = history["cycles"][0]["candidates"][0]

    assert candidate["refs"] == {
        "decisionId": "decision-safe-1",
        "positionId": "position-safe-1",
    }
    serialized = json.dumps(history).lower()
    assert "never-copy-me" not in serialized
    assert "never-public" not in serialized
    assert "client_order_id" not in serialized
    assert history["cycles"][0]["summary"] == {
        "candidateCount": 1,
        "buyCount": 1,
        "blockedCount": 1,
        "executedCount": 0,
        "riskRejectedCount": 1,
        "executionFailureCount": 0,
    }


def test_redacts_sensitive_values_from_previous_history():
    current = cycle("cycle-safe")
    unsafe = cycle("cycle-unsafe")
    unsafe["reasonCode"] = "api_key=secret-value"
    unsafe["candidates"][0]["reasonCodes"] = ["password=hunter2"]
    previous = {"decisionHistory": {"cycles": [unsafe]}}

    history = enrich_snapshot(snapshot(current), previous)["decisionHistory"]
    serialized = json.dumps(history).lower()

    assert "secret-value" not in serialized
    assert "hunter2" not in serialized
    assert history["cycles"][1]["reasonCode"] == "redacted"
    assert history["cycles"][1]["candidates"][0]["reasonCodes"] == ["redacted"]


def test_requires_dashboard_and_phase16_contracts():
    invalid_dashboard = snapshot(cycle("cycle-1"))
    invalid_dashboard["schemaVersion"] = "dashboard-snapshot.v1"
    with pytest.raises(ValueError, match="dashboard-snapshot.v2"):
        enrich_snapshot(invalid_dashboard)

    invalid_observability = snapshot(cycle("cycle-1"))
    invalid_observability["observability"]["schemaVersion"] = "trading-observability.v0"
    with pytest.raises(ValueError, match="trading-observability.v1"):
        enrich_snapshot(invalid_observability)
