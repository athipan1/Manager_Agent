from types import SimpleNamespace

from app.services.analysis_service import (
    extract_current_price_and_stop,
    fundamental_v2_scores,
    score_deep_analysis,
)


def test_extract_current_price_and_stop_returns_nested_values():
    payload = {
        "raw_data": {
            "technical": {
                "data": {
                    "current_price": "123.45",
                    "indicators": {"stop_loss": 120.0},
                }
            }
        }
    }

    assert extract_current_price_and_stop(payload) == (123.45, 120.0)


def test_extract_current_price_and_stop_fails_safe():
    assert extract_current_price_and_stop({}) == (0.0, None)
    assert extract_current_price_and_stop(
        {"raw_data": {"technical": {"data": {"current_price": {}}}}}
    ) == (0.0, None)


def test_fundamental_v2_scores_normalizes_confidence_and_defaults_missing_fields():
    payload = {
        "raw_data": {
            "fundamental": {
                "data": {
                    "confidence_score": 80,
                    "sector": "Technology",
                    "risk_flags": ["confidence_capped"],
                    "comparative_analysis": {"peer_rank": 2},
                }
            }
        }
    }

    assert fundamental_v2_scores(payload) == {
        "composite_score": 0.8,
        "sector": "Technology",
        "risk_flags": ["confidence_capped"],
        "comparative_analysis": {"peer_rank": 2},
    }

    assert fundamental_v2_scores({}) == {
        "composite_score": 0.0,
        "sector": None,
        "risk_flags": [],
        "comparative_analysis": {},
    }


def test_score_deep_analysis_matches_legacy_weighting():
    details = SimpleNamespace(
        technical=SimpleNamespace(score=0.7),
        fundamental=SimpleNamespace(score=0.9),
    )
    payload = {"details": details, "final_verdict": "buy"}

    assert score_deep_analysis(payload, scanner_score=0.5) == {
        "scanner_score": 0.5,
        "technical_score": 0.7,
        "fundamental_score": 0.9,
        "verdict_score": 0.8,
        "final_opportunity_score": 0.75,
    }


def test_score_deep_analysis_uses_scanner_score_when_fundamental_score_missing():
    details = SimpleNamespace(
        technical=SimpleNamespace(score=0.6),
        fundamental=SimpleNamespace(score=0.0),
    )
    payload = {"details": details, "final_verdict": "hold"}

    assert score_deep_analysis(payload, scanner_score=0.4) == {
        "scanner_score": 0.4,
        "technical_score": 0.6,
        "fundamental_score": 0.4,
        "verdict_score": 0.45,
        "final_opportunity_score": 0.465,
    }


def test_score_deep_analysis_exposes_cache_telemetry_without_changing_score():
    details = SimpleNamespace(
        technical=SimpleNamespace(score=0.7),
        fundamental=SimpleNamespace(score=0.9),
    )
    payload = {
        "details": details,
        "final_verdict": "buy",
        "analysis_cache": {
            "policy_version": "manager-deep-analysis-cache-v1",
            "hit": True,
            "one_shot": True,
            "age_seconds": 3.25,
            "ttl_seconds": 900.0,
            "source_correlation_id": "step-19",
            "request_correlation_id": "step-21",
        },
    }

    result = score_deep_analysis(payload, scanner_score=0.5)

    assert result["final_opportunity_score"] == 0.75
    assert result["analysis_cache_policy_version"] == (
        "manager-deep-analysis-cache-v1"
    )
    assert result["analysis_cache_hit"] is True
    assert result["analysis_cache_one_shot"] is True
    assert result["analysis_cache_age_seconds"] == 3.25
    assert result["analysis_cache_ttl_seconds"] == 900.0
    assert result["analysis_cache_source_correlation_id"] == "step-19"
    assert result["analysis_cache_request_correlation_id"] == "step-21"
