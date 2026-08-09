import json
from pathlib import Path

from scripts.enrich_dashboard_snapshot import enrich_snapshot


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def base_snapshot() -> dict:
    return {
        "schemaVersion": "dashboard-snapshot.v2",
        "generatedAt": "2026-08-09T11:48:23Z",
        "workflow": {"conclusion": "success"},
        "runtime": {"mode": "PAPER", "brokerMode": "ALPACA"},
        "cycle": {"status": "controlled_no_trade"},
        "phases": [
            {"name": "scanner", "status": "success", "message": None},
            {"name": "risk", "status": "not_attempted", "message": None},
            {"name": "execution", "status": "not_attempted", "message": None},
        ],
        "account": {
            "cash": None,
            "equity": None,
            "buyingPower": None,
            "valuesMasked": True,
        },
        "positions": [],
        "openOrders": [],
        "signals": [],
        "summary": {},
        "warnings": [],
        "error": None,
        "lastSuccessfulRun": None,
        "freshness": {"isStale": False},
        "privacy": {"mode": "masked", "valuesMasked": True},
    }


def test_enriches_agents_and_risk_from_existing_hourly_evidence(tmp_path):
    write_json(
        tmp_path / "hourly-preflight.json",
        {
            "railway_database": {
                "health": "connected",
                "ready": True,
                "version": "1.1.0",
            }
        },
    )
    write_json(
        tmp_path / "hourly-position-review.json",
        {
            "generated_at": "2026-08-09T11:45:48Z",
            "stage": "existing_positions_reviewed_before_candidates",
            "safe_for_candidate_analysis": True,
            "market_regime": {"regime": "bull", "risk_level": "low"},
            "performance_session_risk": {
                "emergency_halt": False,
                "generated_at": "2026-08-09T11:45:48Z",
            },
            "portfolio_allocation": {"invested_weight": 0.25},
        },
    )
    write_json(
        tmp_path / "hourly-pre-backtest-discovery.json",
        {
            "status": "success",
            "generated_at": "2026-08-09T11:46:00Z",
            "response": {
                "data": {
                    "ranked_candidates": [
                        {
                            "evidence_summary": {
                                "sources": {
                                    "technical": {
                                        "present": True,
                                        "status": "complete",
                                    },
                                    "fundamental": {
                                        "present": True,
                                        "status": "partial",
                                    },
                                }
                            }
                        }
                    ]
                }
            },
        },
    )

    enriched = enrich_snapshot(base_snapshot(), tmp_path)
    agents = {item["id"]: item for item in enriched["agents"]}

    assert agents["manager"]["health"] == "healthy"
    assert agents["manager"]["status"] == "controlled_no_trade"
    assert agents["database"]["health"] == "healthy"
    assert agents["database"]["version"] == "1.1.0"
    assert agents["technical"]["health"] == "healthy"
    assert agents["fundamental"]["health"] == "degraded"
    assert agents["portfolio"]["health"] == "healthy"
    assert agents["market_regime"]["status"] == "regime:bull"
    assert enriched["risk"]["riskLevel"] == "low"
    assert enriched["risk"]["grossExposurePercent"] == 25.0
    assert enriched["risk"]["emergencyHalt"]["active"] is False
    assert enriched["account"]["cash"] is None
    assert enriched["privacy"] == {"mode": "masked", "valuesMasked": True}


def test_backtest_projection_uses_real_result_and_preserves_history(tmp_path):
    write_json(
        tmp_path / "backtest-runtime-contract.json",
        {"timestamp": "2026-08-09T11:46:00Z"},
    )
    write_json(
        tmp_path / "hourly-backtest-result.json",
        {
            "data": {
                "items": [
                    {
                        "symbol": "AAPL",
                        "status": "eligible_strategy_found",
                        "run_id": "run-2",
                        "selected_strategy_id": "momentum-v1",
                        "result": {
                            "initial_equity": 100000,
                            "final_equity": 110000,
                            "metrics": {
                                "sharpe_ratio": 1.4,
                                "win_rate": 0.6,
                                "max_drawdown": -0.08,
                                "total_trades": 20,
                            },
                            "equity_curve": [
                                {
                                    "timestamp": "2026-08-01T00:00:00Z",
                                    "equity": 100000,
                                },
                                {
                                    "timestamp": "2026-08-09T00:00:00Z",
                                    "equity": 110000,
                                },
                            ],
                        },
                    }
                ]
            }
        },
    )
    previous = {
        "backtest": {
            "latestRun": {
                "id": "run-1",
                "status": "success",
                "strategy": "mean-reversion-v1",
                "symbols": ["MSFT"],
                "completedAt": "2026-08-08T00:00:00Z",
                "statistics": {},
            },
            "history": [],
        }
    }

    enriched = enrich_snapshot(base_snapshot(), tmp_path, previous)
    latest = enriched["backtest"]["latestRun"]

    assert latest["id"] == "run-2"
    assert latest["strategy"] == "momentum-v1"
    assert latest["statistics"]["sharpeRatio"] == 1.4
    assert latest["statistics"]["winRatePercent"] == 60.0
    assert latest["statistics"]["maxDrawdownPercent"] == 8.0
    assert len(latest["equityCurve"]) == 2
    assert [row["id"] for row in enriched["backtest"]["history"]] == [
        "run-2",
        "run-1",
    ]


def test_missing_optional_evidence_is_graceful_and_previous_backtest_survives(
    tmp_path,
):
    previous = {
        "backtest": {
            "latestRun": {
                "id": "old-run",
                "status": "success",
                "strategy": "momentum-v1",
                "symbols": ["AAPL"],
                "completedAt": "2026-08-08T00:00:00Z",
                "statistics": {},
            },
            "history": [],
        }
    }

    enriched = enrich_snapshot(base_snapshot(), tmp_path, previous)

    assert [agent["id"] for agent in enriched["agents"]] == [
        "manager",
        "scanner",
        "risk",
        "execution",
    ]
    assert enriched["risk"] is None
    assert enriched["backtest"]["latestRun"]["id"] == "old-run"
    json.dumps(enriched, allow_nan=False)


def test_does_not_copy_sensitive_diagnostics(tmp_path):
    write_json(
        tmp_path / "hourly-position-review.json",
        {
            "market_regime": {"regime": "bull", "risk_level": "low"},
            "performance_session_risk": {
                "emergency_halt": True,
                "emergency_halt_reason": "api_key=super-secret",
                "generated_at": "2026-08-09T11:45:48Z",
            },
        },
    )

    enriched = enrich_snapshot(base_snapshot(), tmp_path)
    serialized = json.dumps(enriched).lower()

    assert "super-secret" not in serialized
    assert enriched["risk"]["emergencyHalt"]["reason"] == "redacted"
