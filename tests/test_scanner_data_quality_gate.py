from datetime import datetime, timezone

import pytest

from app.contracts import StandardAgentResponse
from app.scanner_client import (
    SCANNER_PREFETCH_CACHE,
    _apply_scanner_data_quality_gate,
    _cache_scanner_candidates,
)
from app.services.scanner_data_quality_service import (
    evaluate_scanner_candidate_data_quality,
    scanner_candidate_coverage_ratio,
    scanner_min_data_coverage,
)


def _technical_candidate(symbol="AAPL", coverage=0.95, status="complete", schema="scanner-data-bundle.v1"):
    return {
        "symbol": symbol,
        "confidence_score": 0.9,
        "metadata": {
            "source": "ranked_scanner",
            "details": {
                "data_bundle": {
                    "schema_version": schema,
                    "symbol": symbol,
                    "data_quality": {
                        "status": status,
                        "coverage_ratio": coverage,
                        "missing_components": [],
                        "partial_components": [],
                        "market_missing_fields": [],
                        "market_provider_errors": [],
                    },
                }
            },
        },
    }


def _fundamental_candidate(symbol="MSFT"):
    return {
        "symbol": symbol,
        "candidate_score": 0.88,
        "recommendation_hint": "FUNDAMENTAL_TOP_10",
        "raw_scores": {"evidence_coverage": 0.90},
        "metadata": {
            "source": "real_market_fundamental_discovery",
            "data_bundle": {
                "schema_version": "scanner-data-bundle.v1",
                "symbol": symbol,
                "data_quality": {
                    "status": "partial",
                    "market": {"status": "partial", "coverage_ratio": 0.90},
                    "financial_statements": {
                        "status": "partial",
                        "available_statements": [
                            "annual_income_statement",
                            "annual_balance_sheet",
                            "annual_cash_flow",
                            "quarterly_income_statement",
                            "quarterly_cash_flow",
                        ],
                        "missing_statements": ["quarterly_balance_sheet"],
                    },
                },
            },
        },
    }


def _scanner_response(candidates):
    return StandardAgentResponse(
        status="success",
        agent_type="scanner",
        version="1.3.0",
        timestamp=datetime.now(timezone.utc),
        correlation_id="quality-gate-test",
        data={
            "scan_type": "best_fundamentals",
            "count": len(candidates),
            "candidates": candidates,
            "metadata": {},
            "errors": {},
        },
    )


def test_default_min_coverage_is_80_percent(monkeypatch):
    monkeypatch.delenv("SCANNER_MIN_DATA_COVERAGE", raising=False)
    assert scanner_min_data_coverage() == 0.80


def test_min_coverage_can_be_overridden_and_is_clamped(monkeypatch):
    monkeypatch.setenv("SCANNER_MIN_DATA_COVERAGE", "0.90")
    assert scanner_min_data_coverage() == 0.90
    monkeypatch.setenv("SCANNER_MIN_DATA_COVERAGE", "2")
    assert scanner_min_data_coverage() == 1.0


def test_complete_candidate_above_threshold_passes():
    result = evaluate_scanner_candidate_data_quality(
        _technical_candidate(coverage=0.95),
        min_coverage_ratio=0.80,
    )
    assert result["decision"] == "PASS"
    assert result["allowed"] is True
    assert result["coverage_ratio"] == 0.95


def test_analysis_ready_scope_prevents_optional_enrichment_from_blocking_deep_analysis():
    candidate = _technical_candidate(coverage=0.6667, status="partial")
    quality = candidate["metadata"]["details"]["data_bundle"]["data_quality"]
    quality["missing_components"] = ["sector_rotation", "backtest"]
    quality["analysis"] = {
        "status": "complete",
        "coverage_ratio": 1.0,
        "coverage_scope": "analysis_ready",
        "required_components": ["technical", "market_rank"],
        "complete_components": ["technical", "market_rank"],
        "partial_components": [],
        "missing_components": [],
    }

    result = evaluate_scanner_candidate_data_quality(
        candidate,
        min_coverage_ratio=0.80,
    )

    assert result["decision"] == "PASS"
    assert result["allowed"] is True
    assert result["coverage_ratio"] == 1.0
    assert result["coverage_scope"] == "analysis_ready"
    assert result["legacy_full_coverage_ratio"] == 0.6667
    assert result["min_coverage_ratio"] == 0.80


def test_real_analysis_gap_at_75_percent_still_moves_to_review():
    candidate = _technical_candidate(coverage=1.0, status="complete")
    quality = candidate["metadata"]["details"]["data_bundle"]["data_quality"]
    quality["analysis"] = {
        "status": "partial",
        "coverage_ratio": 0.75,
        "coverage_scope": "analysis_ready",
        "required_components": ["technical", "market_rank"],
        "complete_components": ["market_rank"],
        "partial_components": ["technical"],
        "missing_components": [],
    }

    result = evaluate_scanner_candidate_data_quality(
        candidate,
        min_coverage_ratio=0.80,
    )

    assert result["decision"] == "REVIEW"
    assert result["allowed"] is False
    assert result["coverage_ratio"] == 0.75
    assert result["coverage_scope"] == "analysis_ready"
    assert result["partial_components"] == ["technical"]
    assert result["reason_code"] == "SCANNER_DATA_COVERAGE_BELOW_THRESHOLD"


def test_partial_candidate_below_threshold_moves_to_review():
    result = evaluate_scanner_candidate_data_quality(
        _technical_candidate(coverage=0.79, status="partial"),
        min_coverage_ratio=0.80,
    )
    assert result["decision"] == "REVIEW"
    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_DATA_COVERAGE_BELOW_THRESHOLD"


def test_candidate_without_bundle_moves_to_review():
    result = evaluate_scanner_candidate_data_quality(
        {"symbol": "NVDA", "metadata": {"source": "ranked_scanner"}},
        min_coverage_ratio=0.80,
    )
    assert result["decision"] == "REVIEW"
    assert result["reason_code"] == "SCANNER_DATA_BUNDLE_MISSING"


def test_unknown_bundle_schema_moves_to_review():
    result = evaluate_scanner_candidate_data_quality(
        _technical_candidate(schema="scanner-data-bundle.v2"),
        min_coverage_ratio=0.80,
    )
    assert result["decision"] == "REVIEW"
    assert result["reason_code"] == "SCANNER_DATA_BUNDLE_SCHEMA_UNSUPPORTED"


def test_fundamental_bundle_derives_effective_coverage_from_available_evidence():
    candidate = _fundamental_candidate()
    bundle = candidate["metadata"]["data_bundle"]
    ratio = scanner_candidate_coverage_ratio(candidate, bundle)
    assert ratio == pytest.approx((0.90 + (5 / 6) + 0.90) / 3, abs=1e-4)

    result = evaluate_scanner_candidate_data_quality(
        candidate,
        min_coverage_ratio=0.80,
    )
    assert result["decision"] == "PASS"
    assert result["allowed"] is True
    assert result["coverage_scope"] == "derived_fundamental"


def test_scanner_client_gate_filters_review_candidates_and_preserves_diagnostics(monkeypatch):
    monkeypatch.setenv("SCANNER_MIN_DATA_COVERAGE", "0.80")
    response = _scanner_response(
        [
            _technical_candidate("AAPL", coverage=0.95),
            _technical_candidate("TSLA", coverage=0.60, status="partial"),
        ]
    )

    gated = _apply_scanner_data_quality_gate(response)
    data = gated.data.model_dump(mode="json")

    assert data["count"] == 1
    assert [row["symbol"] for row in data["candidates"]] == ["AAPL"]
    assert data["review_candidates"][0]["symbol"] == "TSLA"
    assert data["review_candidates"][0]["decision"] == "REVIEW"
    summary = data["metadata"]["scanner_data_quality_gate"]
    assert summary["original_count"] == 2
    assert summary["passed_count"] == 1
    assert summary["review_count"] == 1
    assert summary["decision"] == "PARTIAL"
    assert summary["threshold_relaxed"] is False
    assert summary["coverage_scope_counts"] == {"legacy_full_enrichment": 2}


def test_only_quality_passed_candidates_enter_scanner_prefetch_cache(monkeypatch):
    monkeypatch.setenv("SCANNER_MIN_DATA_COVERAGE", "0.80")
    SCANNER_PREFETCH_CACHE.clear()
    gated = _apply_scanner_data_quality_gate(
        _scanner_response(
            [
                _technical_candidate("AAPL", coverage=0.95),
                _technical_candidate("TSLA", coverage=0.40, status="partial"),
            ]
        )
    )

    _cache_scanner_candidates(gated)

    assert "AAPL" in SCANNER_PREFETCH_CACHE
    assert "TSLA" not in SCANNER_PREFETCH_CACHE
