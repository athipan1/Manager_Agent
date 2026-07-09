from __future__ import annotations

from copy import deepcopy

import pytest

from app.portfolio_allocation import classify_strategy_bucket_decision
from app.scanner_policy_router import classify_candidate_strategy_bucket
from app.strategy_bucket_classifier import (
    classify_candidate_strategy_bucket as classify_legacy_candidate,
)


def _scanner_contract(
    *,
    status="suggested",
    primary="value_rebound",
    scores=None,
    tags=None,
    defining=None,
    supporting=None,
    dominance_rule=None,
    policy_version="scanner-bucket-hint-policy-v3",
):
    scores = scores or {
        "core_dividend": 0.55,
        "value_rebound": 0.85,
        "news_momentum": 0.60,
    }
    payload = {
        "bucket_hint_version": "scanner-bucket-hints-v2",
        "bucket_hint_policy_version": policy_version,
        "bucket_hint_status": status,
        "primary_strategy_bucket_hint": primary,
        "primary_strategy_bucket_confidence": (
            scores.get(primary) if primary else None
        ),
        "strategy_bucket_confidence": max(scores.values()),
        "strategy_bucket_hints": [primary] if primary else [],
        "bucket_hint_scores": scores,
        "bucket_hint_defining_evidence": defining or {},
        "bucket_hint_supporting_evidence": supporting or {},
        "bucket_hint_dominance_rule": dominance_rule,
        "bucket_hint_is_binding": False,
        "manager_decision_required": True,
        "tags": list(tags or []),
    }
    return {
        "metadata": dict(payload),
        "raw_scores": {},
        "bucket_hint": dict(payload),
        "tags": list(tags or []),
    }


def _fundamental_response(raw_scores, *, sector=None):
    metrics = {"sector": sector} if sector else {}
    evidence = {
        "evidence_version": "fundamental-evidence-v1",
        "evidence_status": "complete",
        "evidence_completeness_score": 0.95,
        "raw_scores": dict(raw_scores),
        "metrics": metrics,
        "available_fields": sorted(raw_scores),
        "missing_fields": [],
        "missing_critical_metrics": [],
        "evidence_reasons": [],
        "risk_flags": [],
        "provenance": {"analysis_source": "scanner_policy_v3_test"},
        "strategy_bucket_hint": None,
        "bucket_decision_authority": "manager",
        "manager_decision_required": True,
    }
    return {
        "status": "success",
        "version": "1.1.0",
        "data": {
            "action": "buy",
            "confidence_score": 0.85,
            "reason": "test",
            "raw_scores": dict(raw_scores),
            "key_metrics": metrics,
            "fundamental_evidence": evidence,
            "evidence_version": "fundamental-evidence-v1",
            "evidence_status": "complete",
            "bucket_decision_authority": "manager",
            "manager_decision_required": True,
            "strategy_bucket_hint": None,
        },
    }


def _technical_response(*, strength=0.45, walk_forward_passed=True):
    raw_scores = {
        "technical_score": strength,
        "momentum_score": strength,
        "trend_score": strength,
        "indicator_score": strength,
        "technical_vote_score": strength,
        "breakout_ratio": 0.90,
    }
    evidence = {
        "evidence_version": "technical-evidence-v1",
        "evidence_status": "complete",
        "evidence_completeness_score": 0.95,
        "raw_scores": dict(raw_scores),
        "metrics": {},
        "available_fields": sorted(raw_scores),
        "missing_fields": [],
        "evidence_reasons": [],
        "provenance": {
            "walk_forward_passed": walk_forward_passed,
            "validation_status": "test",
        },
        "strategy_bucket_hint": None,
        "bucket_decision_authority": "manager",
        "manager_decision_required": True,
    }
    return {
        "status": "success",
        "version": "1.4.0",
        "data": {
            "action": "buy",
            "confidence_score": strength,
            "reason": "test",
            "raw_scores": dict(raw_scores),
            "technical_evidence": evidence,
            "evidence_version": "technical-evidence-v1",
            "evidence_status": "complete",
            "bucket_decision_authority": "manager",
            "manager_decision_required": True,
            "strategy_bucket_hint": None,
        },
    }


def _candidate(
    symbol,
    raw_scores,
    *,
    sector,
    scanner,
    technical_strength=0.45,
    tags=None,
):
    return {
        "symbol": symbol,
        "tags": list(tags or []),
        "analysis": {
            "ticker": symbol,
            "final_verdict": "buy",
            "status": "complete",
            "details": {},
            "raw_data": {
                "fundamental": _fundamental_response(
                    raw_scores,
                    sector=sector,
                ),
                "technical": _technical_response(
                    strength=technical_strength,
                ),
            },
        },
        "scanner_candidate": scanner,
        "score_breakdown": {"final_opportunity_score": 0.80},
    }


def test_policy_v3_ignores_machine_tags_and_financial_sector_core_bias():
    machine_tags = [
        "bucket-candidate:core_dividend",
        "bucket-candidate:value_rebound",
        "bucket-candidate:news_momentum",
        "bucket-hint:value_rebound",
        "quality",
        "cash-flow",
    ]
    item = _candidate(
        "CINF",
        {
            "quality_score": 0.86,
            "valuation_score": 0.90,
            "growth_score": 1.0,
            "pe_ratio": 10.81,
            "pb_ratio": 1.79,
            "free_cash_flow": 3_092_000_000,
            "debt_to_equity": 0.055,
        },
        sector="Financial Services",
        scanner=_scanner_contract(
            status="suggested",
            primary="value_rebound",
            scores={
                "core_dividend": 0.61,
                "value_rebound": 0.89,
                "news_momentum": 0.70,
            },
            tags=machine_tags,
            dominance_rule="deep_value_without_income_dominance",
        ),
        tags=machine_tags,
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "value_rebound"
    assert decision.status == "classified"
    assert decision.conflict_buckets == ()
    assert "machine_bucket_tags_ignored" in decision.reasons
    assert "financial_services_not_defensive_sector" in decision.reasons
    assert "quality_core_requires_income_identity" in decision.reasons
    assert (
        "growth_only_momentum_requires_technical_corroboration"
        in decision.reasons
    )
    assert not any(
        reason.startswith("tag_evidence:")
        for reason in decision.reasons
    )
    scanner_provenance = decision.evidence_summary["sources"]["scanner"][
        "provenance"
    ]
    assert scanner_provenance["bucket_hint_policy_version"] == (
        "scanner-bucket-hint-policy-v3"
    )
    assert scanner_provenance["generic_tags_supporting_only"] is True
    assert scanner_provenance["ignored_machine_tags"]


def test_scanner_review_is_advisory_not_a_manager_conflict():
    item = _candidate(
        "ACAD",
        {
            "quality_score": 1.0,
            "valuation_score": 0.566667,
            "growth_score": 1.0,
            "pe_ratio": 11.87,
            "pb_ratio": 3.56,
            "free_cash_flow": 105_146_000,
            "debt_to_equity": 0.043,
        },
        sector="Healthcare",
        scanner=_scanner_contract(
            status="review",
            primary=None,
            scores={
                "core_dividend": 0.6192,
                "value_rebound": 0.6279,
                "news_momentum": 0.58,
            },
        ),
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.status != "conflict"
    assert decision.bucket == "value_rebound"
    assert "scanner_review_is_advisory" in decision.reasons
    assert decision.evidence_gate_passed is True


def test_quality_and_cashflow_without_income_identity_do_not_create_core():
    item = _candidate(
        "QUALITY_ONLY",
        {
            "quality_score": 0.95,
            "valuation_score": 0.20,
            "growth_score": 0.20,
            "pe_ratio": 35,
            "pb_ratio": 7,
            "free_cash_flow": 10_000_000,
            "debt_to_equity": 0.20,
        },
        sector="Technology",
        scanner=_scanner_contract(
            status="review",
            primary=None,
            scores={
                "core_dividend": 0.62,
                "value_rebound": 0.30,
                "news_momentum": 0.25,
            },
            tags=["quality", "cash-flow", "stable"],
        ),
        tags=["quality", "cash-flow", "stable"],
    )

    decision = classify_strategy_bucket_decision(item)

    assert not (
        decision.bucket == "core_dividend"
        and decision.status == "classified"
    )
    assert "quality_core_requires_income_identity" in decision.reasons


def test_explicit_dividend_identity_still_classifies_core():
    item = _candidate(
        "CORE",
        {
            "quality_score": 0.90,
            "valuation_score": 0.45,
            "growth_score": 0.30,
            "dividend_yield": 0.035,
            "pe_ratio": 22,
            "pb_ratio": 4,
            "free_cash_flow": 2_000_000,
            "debt_to_equity": 0.40,
        },
        sector="Consumer Defensive",
        scanner=_scanner_contract(
            status="suggested",
            primary="core_dividend",
            scores={
                "core_dividend": 0.86,
                "value_rebound": 0.45,
                "news_momentum": 0.35,
            },
            defining={
                "core_dividend": [
                    "dividend_yield:0.0350",
                    "defensive_or_income_sector:consumer defensive",
                ]
            },
            dominance_rule="quality_income_dominance",
        ),
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "core_dividend"
    assert decision.status == "classified"
    assert any(
        reason.startswith("dividend_yield:")
        for reason in decision.reasons
    )


def test_true_scanner_policy_v3_conflict_remains_fail_closed():
    item = _candidate(
        "TRUE_CONFLICT",
        {
            "quality_score": 0.80,
            "valuation_score": 0.80,
            "growth_score": 0.80,
            "pe_ratio": 14,
            "pb_ratio": 1.4,
        },
        sector="Technology",
        scanner=_scanner_contract(
            status="conflict",
            primary=None,
            scores={
                "core_dividend": 0.20,
                "value_rebound": 0.82,
                "news_momentum": 0.81,
            },
        ),
        technical_strength=0.80,
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "unassigned"
    assert decision.status == "conflict"
    assert decision.evidence_gate_passed is False
    assert "scanner_internal_bucket_conflict" in decision.reasons


def test_legacy_scanner_payload_keeps_original_classifier_behavior():
    scanner = _scanner_contract(
        status="suggested",
        primary="value_rebound",
        policy_version=None,
    )
    item = _candidate(
        "LEGACY",
        {
            "quality_score": 0.72,
            "valuation_score": 0.90,
            "growth_score": 0.25,
            "pe_ratio": 11,
            "pb_ratio": 1.1,
            "free_cash_flow": 500_000,
            "debt_to_equity": 0.8,
        },
        sector="Financial Services",
        scanner=scanner,
    )

    routed = classify_candidate_strategy_bucket(deepcopy(item))
    legacy = classify_legacy_candidate(deepcopy(item))

    assert routed.as_dict() == legacy.as_dict()


HOURLY_FIXTURES = {
    "ACGL": (0.86, 0.90, 1.0, 7.9139, 1.5350, "Financial Services"),
    "BKNG": (0.80, 0.90, 1.0, 23.9739, -15.5825, "Consumer Cyclical"),
    "ADBE": (0.94, 0.6667, 1.0, 12.6758, 7.6537, "Technology"),
    "CINF": (0.86, 0.6667, 1.0, 10.8139, 1.7863, "Financial Services"),
    "ACIC": (0.94, 0.6667, 1.0, 5.3814, 1.6652, "Financial Services"),
    "CGEN": (1.0, 0.90, 1.0, 6.3421, 2.3909, "Healthcare"),
    "BFC": (0.74, 0.90, 1.0, 20.7980, 1.9871, "Financial Services"),
    "ACAD": (1.0, 0.5667, 1.0, 11.8721, 3.5641, "Healthcare"),
}


@pytest.mark.parametrize(
    "symbol,fixture",
    list(HOURLY_FIXTURES.items()),
)
def test_hourly_candidates_no_longer_conflict_from_broad_evidence(
    symbol,
    fixture,
):
    quality, valuation, growth, pe_ratio, pb_ratio, sector = fixture
    scanner_status = "review" if symbol in {"BKNG", "ACAD"} else "suggested"
    primary = None if scanner_status == "review" else "value_rebound"
    scanner = _scanner_contract(
        status=scanner_status,
        primary=primary,
        scores={
            "core_dividend": 0.62,
            "value_rebound": 0.84,
            "news_momentum": 0.70,
        },
        dominance_rule=(
            "deep_value_without_income_dominance"
            if primary
            else None
        ),
    )
    item = _candidate(
        symbol,
        {
            "quality_score": quality,
            "valuation_score": valuation,
            "growth_score": growth,
            "pe_ratio": pe_ratio,
            "pb_ratio": pb_ratio,
            "free_cash_flow": 1_000_000,
            "debt_to_equity": 0.50,
        },
        sector=sector,
        scanner=scanner,
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.status != "conflict"
    assert decision.bucket == "value_rebound"
    assert decision.evidence_gate_passed is True
