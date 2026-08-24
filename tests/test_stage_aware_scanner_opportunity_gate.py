from datetime import datetime, timezone

from app.contracts import StandardAgentResponse
from app.scanner_client import _apply_scanner_candidate_gates
from app.services.scanner_opportunity_service import (
    evaluate_scanner_candidate_opportunity,
)


def _candidate(
    symbol: str,
    *,
    opportunity_score: float,
    status: str = "review",
    workflow_status: str = "evidence_review",
    quote_status: str = "fresh",
    spread_structurally_valid: bool = True,
    fail_closed: bool = False,
):
    return {
        "symbol": symbol,
        "confidence_score": 0.90,
        "metadata": {
            "source": "real_market_fundamental_discovery",
            "details": {
                "data_bundle": {
                    "schema_version": "scanner-data-bundle.v1",
                    "symbol": symbol,
                    "data_quality": {
                        "status": "complete",
                        "coverage_ratio": 0.95,
                        "missing_components": [],
                        "partial_components": [],
                        "market_missing_fields": [],
                        "market_provider_errors": [],
                    },
                    "opportunity_profile": {
                        "schema_version": "scanner-opportunity-profile.v1",
                        "status": status,
                        "workflow_status": workflow_status,
                        "opportunity_score": opportunity_score,
                        "is_binding": False,
                        "manager_decision_required": True,
                        "fail_closed": fail_closed,
                        "preferred_strategy_hint": "trend_following",
                        "strategy_affinity": {
                            "trend_following": 0.5,
                            "breakout": 0.4,
                            "mean_reversion": 0.3,
                        },
                        "execution_context": {
                            "current_price": 100.0,
                            "average_volume": 2_000_000,
                            "estimated_dollar_volume": 200_000_000.0,
                            "spread_bps": 1000.0 if not spread_structurally_valid else 8.0,
                            "quote_status": quote_status,
                            "market_session": "closed" if quote_status == "market_closed" else "regular",
                            "market_open": quote_status != "market_closed",
                        },
                        "evidence_quality": {
                            "atr_available": False,
                            "relative_volume_available": True,
                            "spread_available": True,
                            "quote_timestamp_available": True,
                            "liquid_spread_sane": spread_structurally_valid,
                            "spread_structurally_valid": spread_structurally_valid,
                            "coverage_ratio": 0.5,
                        },
                        "reasons": ["missing_atr"],
                    },
                }
            },
        },
    }


def _response(candidates):
    return StandardAgentResponse(
        status="success",
        agent_type="scanner",
        version="1.3.0",
        timestamp=datetime.now(timezone.utc),
        correlation_id="stage-aware-gate-test",
        data={
            "scan_type": "best_fundamentals",
            "count": len(candidates),
            "candidates": candidates,
            "metadata": {},
            "errors": {},
        },
    )


def test_broad_discovery_defers_execution_opportunity_filter(monkeypatch):
    monkeypatch.setenv("SCANNER_MIN_DATA_COVERAGE", "0.80")
    monkeypatch.setenv("SCANNER_OPPORTUNITY_PROFILE_REQUIRED", "true")
    monkeypatch.setenv("SCANNER_MIN_OPPORTUNITY_SCORE", "0.70")

    response = _response(
        [
            _candidate("NVDA", opportunity_score=0.245),
            _candidate("SMCI", opportunity_score=0.35),
        ]
    )

    gated = _apply_scanner_candidate_gates(
        response,
        opportunity_advisory_only=True,
    )
    data = gated.data.model_dump(mode="json")
    summary = data["metadata"]["scanner_opportunity_gate"]

    assert [row["symbol"] for row in data["candidates"]] == ["NVDA", "SMCI"]
    assert data["count"] == 2
    assert summary["passed_count"] == 0
    assert summary["review_count"] == 2
    assert summary["effective_passed_count"] == 2
    assert summary["deferred_review_count"] == 2
    assert summary["gate_mode"] == "advisory_discovery"
    assert summary["advisory_only"] is True


def test_explicit_symbol_gate_remains_blocking(monkeypatch):
    monkeypatch.setenv("SCANNER_MIN_DATA_COVERAGE", "0.80")
    monkeypatch.setenv("SCANNER_OPPORTUNITY_PROFILE_REQUIRED", "true")
    monkeypatch.setenv("SCANNER_MIN_OPPORTUNITY_SCORE", "0.70")

    gated = _apply_scanner_candidate_gates(
        _response([_candidate("NVDA", opportunity_score=0.245)])
    )
    data = gated.data.model_dump(mode="json")
    summary = data["metadata"]["scanner_opportunity_gate"]

    assert data["candidates"] == []
    assert data["count"] == 0
    assert summary["gate_mode"] == "blocking_execution"
    assert summary["effective_passed_count"] == 0


def test_market_closed_quote_wins_over_after_hours_spread_artifact():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(
            "META",
            opportunity_score=0.72,
            status="review",
            workflow_status="market_closed",
            quote_status="market_closed",
            spread_structurally_valid=False,
            fail_closed=False,
        ),
        profile_required=True,
        live_spread_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_MARKET_CLOSED"
    assert result["controlled_no_trade"] is True
    assert result["workflow_failure"] is False


def test_explicit_fail_closed_still_wins_even_when_market_is_closed():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(
            "META",
            opportunity_score=0.72,
            status="avoid",
            workflow_status="market_closed",
            quote_status="market_closed",
            spread_structurally_valid=False,
            fail_closed=True,
        ),
        profile_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_FAIL_CLOSED"
