from copy import deepcopy

from app.analysis_evidence import build_analysis_evidence_summary
from app.discover_allocation import (
    enrich_ranked_candidates_with_buckets,
)
from app.discover_report_builder import (
    build_position_analysis_payloads,
    build_selected_positions,
)
from app.portfolio_allocation import (
    build_strategy_allocation_plan,
    classify_strategy_bucket_decision,
)
from app.discover_allocation import select_candidates_by_bucket


def _scanner_contract(
    *,
    primary=None,
    confidence=0.0,
    status="insufficient_evidence",
    version="scanner-bucket-hints-v2",
):
    scores = {primary: confidence} if primary else {
        "core_dividend": 0.0,
        "value_rebound": 0.0,
        "news_momentum": 0.0,
    }
    metadata = {
        "bucket_hint_version": version,
        "bucket_hint_status": status,
        "primary_strategy_bucket_hint": primary,
        "primary_strategy_bucket_confidence": (
            confidence if primary else None
        ),
        "strategy_bucket_confidence": confidence,
        "strategy_bucket_hints": [primary] if primary else [],
        "bucket_hint_scores": scores,
        "bucket_hint_is_binding": False,
        "manager_decision_required": True,
        "tags": [],
    }
    return {
        "metadata": metadata,
        "raw_scores": {},
        "bucket_hint": dict(metadata),
    }


def _fundamental_response(
    *,
    raw_scores=None,
    metrics=None,
    status="complete",
    version="fundamental-evidence-v1",
    authority="manager",
    manager_required=True,
    strategy_bucket_hint=None,
):
    evidence = {
        "evidence_version": version,
        "evidence_status": status,
        "evidence_completeness_score": 0.9,
        "raw_scores": raw_scores or {},
        "metrics": metrics or {},
        "available_fields": sorted((raw_scores or {}).keys()),
        "missing_fields": [],
        "missing_critical_metrics": [],
        "evidence_reasons": [],
        "risk_flags": [],
        "provenance": {"analysis_source": "test"},
        "strategy_bucket_hint": strategy_bucket_hint,
        "bucket_decision_authority": authority,
        "manager_decision_required": manager_required,
    }
    return {
        "status": "success",
        "version": "1.1.0",
        "data": {
            "action": "buy",
            "confidence_score": 0.8,
            "reason": "test",
            "raw_scores": raw_scores or {},
            "fundamental_evidence": evidence,
            "evidence_version": version,
            "evidence_status": status,
            "bucket_decision_authority": authority,
            "manager_decision_required": manager_required,
            "strategy_bucket_hint": strategy_bucket_hint,
        },
    }


def _technical_response(
    *,
    raw_scores=None,
    metrics=None,
    status="complete",
    version="technical-evidence-v1",
    authority="manager",
    manager_required=True,
    strategy_bucket_hint=None,
    walk_forward_passed=True,
):
    evidence = {
        "evidence_version": version,
        "evidence_status": status,
        "evidence_completeness_score": 0.9,
        "raw_scores": raw_scores or {},
        "metrics": metrics or {},
        "available_fields": sorted((raw_scores or {}).keys()),
        "missing_fields": [],
        "evidence_reasons": [],
        "provenance": {
            "walk_forward_passed": walk_forward_passed,
            "validation_status": "test",
        },
        "strategy_bucket_hint": strategy_bucket_hint,
        "bucket_decision_authority": authority,
        "manager_decision_required": manager_required,
    }
    return {
        "status": "success",
        "version": "1.4.0",
        "data": {
            "action": "buy",
            "confidence_score": 0.75,
            "reason": "test",
            "raw_scores": raw_scores or {},
            "technical_evidence": evidence,
            "evidence_version": version,
            "evidence_status": status,
            "bucket_decision_authority": authority,
            "manager_decision_required": manager_required,
            "strategy_bucket_hint": strategy_bucket_hint,
        },
    }


def _candidate(
    symbol="TEST",
    *,
    scanner=None,
    fundamental=None,
    technical=None,
    score=0.8,
):
    raw_data = {}
    if fundamental is not None:
        raw_data["fundamental"] = fundamental
    if technical is not None:
        raw_data["technical"] = technical
    return {
        "symbol": symbol,
        "analysis": {
            "ticker": symbol,
            "final_verdict": "buy",
            "status": "complete",
            "details": {},
            "raw_data": raw_data,
        },
        "scanner_candidate": scanner or _scanner_contract(),
        "score_breakdown": {"final_opportunity_score": score},
    }


def test_adapter_accepts_all_supported_contracts():
    item = _candidate(
        scanner=_scanner_contract(
            primary="value_rebound",
            confidence=0.82,
            status="suggested",
        ),
        fundamental=_fundamental_response(
            raw_scores={
                "quality_score": 0.75,
                "valuation_score": 0.90,
                "growth_score": 0.30,
                "pe_ratio": 12,
                "pb_ratio": 1.2,
                "free_cash_flow": 1_000_000,
                "debt_to_equity": 0.7,
            },
        ),
        technical=_technical_response(
            raw_scores={
                "technical_score": 0.55,
                "momentum_score": 0.50,
                "trend_score": 0.50,
                "indicator_score": 0.50,
                "technical_vote_score": 0.50,
                "breakout_ratio": 0.90,
            },
        ),
    )

    summary = build_analysis_evidence_summary(item)

    assert summary["mode"] == "versioned"
    assert summary["gate_required"] is True
    assert summary["gate_passed"] is True
    assert summary["blocking_issues"] == []
    assert summary["evidence_versions"] == {
        "scanner": "scanner-bucket-hints-v2",
        "fundamental": "fundamental-evidence-v1",
        "technical": "technical-evidence-v1",
    }


def test_value_evidence_classifies_value_rebound():
    item = _candidate(
        symbol="VALUE",
        scanner=_scanner_contract(
            primary="value_rebound",
            confidence=0.82,
            status="suggested",
        ),
        fundamental=_fundamental_response(
            raw_scores={
                "quality_score": 0.72,
                "valuation_score": 0.91,
                "growth_score": 0.25,
                "pe_ratio": 11,
                "pb_ratio": 1.1,
                "free_cash_flow": 500_000,
                "debt_to_equity": 0.8,
            },
        ),
        technical=_technical_response(
            raw_scores={
                "technical_score": 0.52,
                "momentum_score": 0.48,
                "trend_score": 0.50,
                "indicator_score": 0.50,
                "technical_vote_score": 0.50,
                "breakout_ratio": 0.90,
            },
        ),
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "value_rebound"
    assert decision.status == "classified"
    assert decision.confidence >= 0.70
    assert decision.classifier_version == "manager-strategy-bucket-v3"
    assert decision.evidence_gate_passed is True
    assert any("valuation_score" in reason for reason in decision.reasons)


def test_quality_dividend_evidence_classifies_core():
    item = _candidate(
        symbol="CORE",
        scanner=_scanner_contract(
            primary="core_dividend",
            confidence=0.80,
            status="suggested",
        ),
        fundamental=_fundamental_response(
            raw_scores={
                "quality_score": 0.90,
                "valuation_score": 0.45,
                "growth_score": 0.35,
                "dividend_yield": 0.035,
                "free_cash_flow": 2_000_000,
                "debt_to_equity": 0.4,
            },
            metrics={"sector": "Consumer Defensive"},
        ),
        technical=_technical_response(
            raw_scores={
                "technical_score": 0.58,
                "momentum_score": 0.55,
                "trend_score": 0.60,
                "indicator_score": 0.55,
                "technical_vote_score": 0.50,
                "breakout_ratio": 0.92,
            },
        ),
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "core_dividend"
    assert decision.status == "classified"
    assert decision.evidence_gate_passed is True
    assert any("dividend_yield" in reason for reason in decision.reasons)


def test_growth_and_technical_evidence_classifies_momentum():
    item = _candidate(
        symbol="MOMO",
        scanner=_scanner_contract(
            primary="news_momentum",
            confidence=0.84,
            status="suggested",
        ),
        fundamental=_fundamental_response(
            raw_scores={
                "quality_score": 0.65,
                "valuation_score": 0.30,
                "growth_score": 0.88,
                "pe_ratio": 45,
                "pb_ratio": 8,
            },
        ),
        technical=_technical_response(
            raw_scores={
                "technical_score": 0.82,
                "momentum_score": 0.88,
                "trend_score": 0.80,
                "indicator_score": 0.84,
                "technical_vote_score": 0.80,
                "breakout_ratio": 0.99,
            },
        ),
        score=0.85,
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "news_momentum"
    assert decision.status == "classified"
    assert decision.evidence_gate_passed is True
    assert any(
        "growth_technical_corroboration" in reason
        for reason in decision.reasons
    )


def test_unsupported_evidence_version_is_invalid():
    item = _candidate(
        scanner=_scanner_contract(),
        fundamental=_fundamental_response(
            version="fundamental-evidence-v999",
        ),
        technical=_technical_response(),
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "unassigned"
    assert decision.status == "invalid"
    assert decision.evidence_gate_passed is False
    assert any(
        "unsupported_fundamental_evidence_version" in reason
        for reason in decision.reasons
    )


def test_child_agent_bucket_authority_violation_is_invalid():
    item = _candidate(
        scanner=_scanner_contract(),
        fundamental=_fundamental_response(
            authority="fundamental",
            strategy_bucket_hint="value_rebound",
        ),
        technical=_technical_response(),
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "unassigned"
    assert decision.status == "invalid"
    assert decision.evidence_gate_passed is False
    assert any(
        "fundamental_bucket_decision_authority_must_be_manager"
        in reason
        for reason in decision.reasons
    )
    assert any(
        "fundamental_must_not_assign_strategy_bucket" in reason
        for reason in decision.reasons
    )


def test_missing_technical_contract_blocks_new_buy():
    item = _candidate(
        scanner=_scanner_contract(
            primary="value_rebound",
            confidence=0.90,
            status="suggested",
        ),
        fundamental=_fundamental_response(
            raw_scores={
                "valuation_score": 0.95,
                "pe_ratio": 10,
                "pb_ratio": 1.0,
            },
        ),
        technical=None,
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "unassigned"
    assert decision.status == "evidence_insufficient"
    assert decision.allows_new_entry is False
    assert "missing_versioned_technical_evidence" in decision.reasons


def test_insufficient_fundamental_evidence_blocks_new_buy():
    item = _candidate(
        scanner=_scanner_contract(
            primary="news_momentum",
            confidence=0.90,
            status="suggested",
        ),
        fundamental=_fundamental_response(status="insufficient"),
        technical=_technical_response(
            raw_scores={
                "technical_score": 0.90,
                "momentum_score": 0.90,
                "trend_score": 0.85,
                "technical_vote_score": 0.80,
                "breakout_ratio": 0.99,
            },
        ),
    )

    decision = classify_strategy_bucket_decision(item)

    assert decision.bucket == "unassigned"
    assert decision.status == "evidence_insufficient"
    assert decision.evidence_gate_passed is False
    assert "fundamental_evidence_insufficient" in decision.reasons


def test_walk_forward_failure_reduces_momentum_confidence():
    base = _candidate(
        scanner=_scanner_contract(status="insufficient_evidence"),
        fundamental=_fundamental_response(
            raw_scores={
                "quality_score": 0.55,
                "valuation_score": 0.25,
                "growth_score": 0.82,
                "pe_ratio": 40,
                "pb_ratio": 7,
            },
        ),
        technical=_technical_response(
            raw_scores={
                "technical_score": 0.82,
                "momentum_score": 0.86,
                "trend_score": 0.80,
                "indicator_score": 0.82,
                "technical_vote_score": 0.80,
                "breakout_ratio": 0.99,
            },
            walk_forward_passed=True,
        ),
        score=0.85,
    )
    failed = deepcopy(base)
    failed_evidence = failed["analysis"]["raw_data"]["technical"][
        "data"
    ]["technical_evidence"]
    failed_evidence["provenance"]["walk_forward_passed"] = False

    passed_decision = classify_strategy_bucket_decision(base)
    failed_decision = classify_strategy_bucket_decision(failed)

    assert passed_decision.bucket == "news_momentum"
    assert failed_decision.confidence < passed_decision.confidence


def test_evidence_summary_is_forwarded_to_risk_payload():
    item = _candidate(
        symbol="CINF",
        scanner=_scanner_contract(
            primary="value_rebound",
            confidence=0.85,
            status="suggested",
        ),
        fundamental=_fundamental_response(
            raw_scores={
                "quality_score": 0.78,
                "valuation_score": 0.90,
                "growth_score": 0.30,
                "pe_ratio": 12,
                "pb_ratio": 1.2,
                "free_cash_flow": 1_000_000,
                "debt_to_equity": 0.6,
            },
        ),
        technical=_technical_response(
            raw_scores={
                "technical_score": 0.60,
                "momentum_score": 0.55,
                "trend_score": 0.60,
                "indicator_score": 0.55,
                "technical_vote_score": 0.50,
                "breakout_ratio": 0.92,
            },
        ),
    )
    ranked = enrich_ranked_candidates_with_buckets([item])
    plan = build_strategy_allocation_plan(ranked, 100_000)
    selection = select_candidates_by_bucket(ranked, min_final_score=0.55)
    selected = build_selected_positions(
        ranked=ranked,
        allocation_plan=plan,
        bucket_selection=selection,
    )
    payloads = build_position_analysis_payloads(
        ranked=ranked,
        selected_positions=selected,
    )

    assert selected[0]["strategy_bucket"] == "value_rebound"
    assert selected[0]["evidence_gate_passed"] is True
    assert payloads[0]["strategy_bucket"] == "value_rebound"
    assert payloads[0]["evidence_versions"]["scanner"] == (
        "scanner-bucket-hints-v2"
    )
    assert payloads[0]["fundamental_evidence_status"] == "complete"
    assert payloads[0]["technical_evidence_status"] == "complete"
    assert payloads[0]["portfolio_context"]["evidence_gate_passed"] is True
    assert payloads[0]["classification_inputs"]["fundamental"][
        "pe_ratio"
    ] == 12
