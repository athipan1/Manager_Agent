import json
from pathlib import Path

from scripts.enrich_trading_observability import STAGE_ORDER, enrich_snapshot


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def snapshot(*, reason: str = "no_preselected_backtest_symbols") -> dict:
    return {
        "schemaVersion": "dashboard-snapshot.v2",
        "generatedAt": "2026-08-09T11:48:23Z",
        "workflow": {"runId": 12345, "conclusion": "success"},
        "cycle": {
            "id": "cycle-1",
            "status": "controlled_no_trade",
            "candidateCount": 1,
            "executionAttempted": False,
            "executionStatus": "not_attempted",
            "executionReason": reason,
            "partialFillDetected": False,
        },
        "phases": [
            {"name": "scanner", "status": "success", "message": None},
            {"name": "backtest", "status": "skipped", "message": None},
            {"name": "risk", "status": "not_attempted", "message": reason},
            {"name": "execution", "status": "not_attempted", "message": reason},
        ],
    }


def test_projects_bounded_decision_path_and_candidate_reasons(tmp_path):
    write_json(
        tmp_path / "hourly-preflight.json",
        {
            "portfolio_cycle_id": "cycle-1",
            "correlation_id": "corr-1",
        },
    )
    write_json(
        tmp_path / "hourly-position-review.json",
        {
            "generated_at": "2026-08-09T11:45:49Z",
            "market_regime": {
                "regime": "bull",
                "risk_level": "low",
                "confidence_score": 0.77,
            },
            "position_decisions": [],
            "safe_for_candidate_analysis": True,
        },
    )
    write_json(
        tmp_path / "hourly-pre-backtest-discovery.json",
        {
            "status": "success",
            "generated_at": "2026-08-09T11:45:54Z",
            "response": {
                "data": {
                    "scanner_count": 1,
                    "risk_approvals": [],
                    "execution": {"status": "not_requested"},
                    "ranked_candidates": [
                        {
                            "symbol": "BANX",
                            "rank": 1,
                            "final_verdict": "buy",
                            "strategy_bucket": "value_rebound",
                            "allows_new_entry": True,
                            "evidence_gate_passed": True,
                            "score_breakdown": {"final_opportunity_score": 0.638},
                            "investability_gate": {
                                "allowed": False,
                                "status": "block",
                                "rejection_codes": [
                                    "investability_market_cap_below_minimum",
                                    "investability_average_dollar_volume_below_minimum",
                                ],
                                "warning_codes": ["investability_spread_missing"],
                                "metrics": {"market_cap": 123, "current_price": 20.5},
                            },
                        }
                    ],
                }
            },
        },
    )

    enriched = enrich_snapshot(snapshot(), tmp_path)
    observability = enriched["observability"]
    current = observability["current"]

    assert observability["schemaVersion"] == "trading-observability.v1"
    assert current["source"] == "hourly_artifact"
    assert current["correlationId"] == "corr-1"
    assert [stage["id"] for stage in current["stages"]] == list(STAGE_ORDER)
    assert current["stages"][0]["summary"]["candidateCount"] == 1
    assert current["stages"][2]["summary"] == {
        "regime": "bull",
        "riskLevel": "low",
        "confidence": 0.77,
    }
    assert current["candidates"] == [
        {
            "symbol": "BANX",
            "rank": 1,
            "verdict": "buy",
            "finalScore": 0.638,
            "strategyBucket": "value_rebound",
            "status": "blocked",
            "stageReached": "scanner",
            "reasonCodes": [
                "investability_market_cap_below_minimum",
                "investability_average_dollar_volume_below_minimum",
                "investability_spread_missing",
            ],
        }
    ]
    assert "market_cap" not in json.dumps(observability)
    assert observability["lastMeaningful"] == current


def test_maps_backtest_risk_and_execution_outcomes_without_raw_payloads(tmp_path):
    write_json(tmp_path / "hourly-preflight.json", {"correlation_id": "corr-2"})
    write_json(
        tmp_path / "hourly-pre-backtest-discovery.json",
        {
            "status": "success",
            "response": {
                "data": {
                    "scanner_count": 1,
                    "ranked_candidates": [
                        {
                            "symbol": "AAPL",
                            "rank": 1,
                            "final_verdict": "buy",
                            "allows_new_entry": True,
                            "evidence_gate_passed": True,
                            "strategy_bucket": "core_dividend",
                            "score_breakdown": {"final_opportunity_score": 0.8},
                        }
                    ],
                    "risk_approvals": [
                        {
                            "symbol": "AAPL",
                            "approved": False,
                            "status": "risk_rejected",
                            "reason_code": "max_position_exposure",
                            "diagnostics": {"secret_key": "must-not-copy"},
                        }
                    ],
                    "execution": {"status": "not_attempted"},
                }
            },
        },
    )
    write_json(
        tmp_path / "hourly-backtest-result.json",
        {
            "data": {
                "items": [
                    {
                        "symbol": "AAPL",
                        "status": "eligible_strategy_found",
                        "result": {"raw_trades": [1, 2, 3]},
                    }
                ]
            }
        },
    )

    enriched = enrich_snapshot(snapshot(reason="risk_rejected"), tmp_path)
    current = enriched["observability"]["current"]
    candidate = current["candidates"][0]

    assert candidate["status"] == "blocked"
    assert candidate["stageReached"] == "risk"
    assert candidate["reasonCodes"] == ["max_position_exposure"]
    assert current["stages"][1]["status"] == "success"
    assert current["stages"][1]["summary"] == {
        "attemptedCount": 1,
        "eligibleCount": 1,
    }
    assert current["stages"][5]["status"] == "blocked"
    serialized = json.dumps(current).lower()
    assert "must-not-copy" not in serialized
    assert "raw_trades" not in serialized


def test_metadata_only_cycle_carries_forward_last_meaningful_cycle(tmp_path):
    previous_cycle = {
        "source": "hourly_artifact",
        "flowKind": "decision_path",
        "correlationId": "corr-old",
        "cycleId": "cycle-old",
        "workflowRunId": 99,
        "observedAt": "2026-08-09T10:00:00Z",
        "status": "controlled_no_trade",
        "reasonCode": "market_closed",
        "stages": [],
        "candidates": [{"symbol": "AAPL"}],
    }
    previous = {
        "observability": {
            "schemaVersion": "trading-observability.v1",
            "current": previous_cycle,
            "lastMeaningful": previous_cycle,
        }
    }
    current_snapshot = snapshot(reason="scheduled_paper_cycle_not_authorized")
    current_snapshot["cycle"]["id"] = None
    current_snapshot["workflow"]["conclusion"] = "skipped"

    enriched = enrich_snapshot(current_snapshot, tmp_path, previous)
    observability = enriched["observability"]

    assert observability["current"]["source"] == "workflow_metadata"
    assert observability["current"]["reasonCode"] == "scheduled_paper_cycle_not_authorized"
    assert [stage["id"] for stage in observability["current"]["stages"]] == list(STAGE_ORDER)
    assert observability["current"]["candidates"] == []
    assert observability["lastMeaningful"] == previous_cycle


def test_redacts_sensitive_reason_codes(tmp_path):
    write_json(tmp_path / "hourly-preflight.json", {"correlation_id": "corr-3"})
    write_json(
        tmp_path / "hourly-pre-backtest-discovery.json",
        {
            "status": "success",
            "response": {
                "data": {
                    "scanner_count": 1,
                    "ranked_candidates": [
                        {
                            "symbol": "TEST",
                            "rank": 1,
                            "final_verdict": "buy",
                            "allows_new_entry": True,
                            "evidence_gate_passed": True,
                            "score_breakdown": {"final_opportunity_score": 0.7},
                            "investability_gate": {
                                "allowed": False,
                                "rejection_codes": ["api_key=super-secret"],
                            },
                        }
                    ],
                }
            },
        },
    )

    enriched = enrich_snapshot(snapshot(), tmp_path)
    serialized = json.dumps(enriched["observability"]).lower()
    assert "super-secret" not in serialized
    assert enriched["observability"]["current"]["candidates"][0]["reasonCodes"] == [
        "redacted"
    ]
