from __future__ import annotations

from typing import Any, Mapping

from .scanner_policy_classifier import (
    AUTO_CLASSIFY_THRESHOLD,
    CLASSIFIER_VERSION,
    CONFLICT_MARGIN,
    CONFLICT_SCORE_THRESHOLD,
    CORE_DIVIDEND,
    KNOWN_BUCKETS,
    MANAGER_SCANNER_POLICY_VERSION,
    NEWS_MOMENTUM,
    REVIEW_THRESHOLD,
    SCANNER_HINT_CONTRACT_VERSION,
    SCANNER_HINT_POLICY_VERSION,
    StrategyBucketClassification,
    UNASSIGNED,
    VALUE_REBOUND,
    _classify_candidate_strategy_bucket,
    _scanner_policy_context,
    classify_candidate_strategy_bucket as _classify_policy_v3,
)


def _resolve_sector_quality_value_overlap(
    decision: StrategyBucketClassification,
) -> StrategyBucketClassification:
    """Prefer explicit value evidence over sector/quality-only Core evidence."""
    if (
        decision.status != "conflict"
        or set(decision.conflict_buckets)
        != {CORE_DIVIDEND, VALUE_REBOUND}
    ):
        return decision

    reasons = tuple(str(reason) for reason in decision.reasons)
    has_dividend_identity = any(
        reason.startswith("dividend_yield:")
        for reason in reasons
    )
    strong_value_reasons = tuple(
        reason
        for reason in reasons
        if reason.startswith("low_pe_ratio:")
        or reason.startswith("low_pb_ratio:")
        or reason.startswith("valuation_score:")
        or reason == "scanner_primary_hint:value_rebound"
        or reason == "scanner_policy_primary:value_rebound"
    )
    if has_dividend_identity or not strong_value_reasons:
        return decision

    return StrategyBucketClassification(
        bucket=VALUE_REBOUND,
        confidence=decision.confidence,
        reasons=(
            "value_evidence_overrides_sector_quality_only_core",
            *strong_value_reasons,
            *(
                reason
                for reason in reasons
                if reason.startswith("scanner_")
                or reason.startswith("machine_")
                or reason.startswith("financial_services_")
                or reason.startswith("growth_only_")
            ),
        ),
        classifier_version=decision.classifier_version,
        status="classified",
        proposed_bucket=VALUE_REBOUND,
        source="manager_scanner_policy_v3_overlap_resolution",
        conflict_buckets=(),
        evidence_gate_passed=decision.evidence_gate_passed,
        evidence_summary=decision.evidence_summary,
    )


def classify_candidate_strategy_bucket(
    item: Mapping[str, Any],
) -> StrategyBucketClassification:
    """Use policy-v3 interpretation only for an explicit Scanner v3 payload."""
    policy = _scanner_policy_context(item)
    policy_v3 = (
        policy.get("contract_version") == SCANNER_HINT_CONTRACT_VERSION
        and policy.get("policy_version") == SCANNER_HINT_POLICY_VERSION
    )
    if not policy_v3:
        return _classify_candidate_strategy_bucket(item)
    decision = _classify_policy_v3(item)
    return _resolve_sector_quality_value_overlap(decision)


__all__ = [
    "AUTO_CLASSIFY_THRESHOLD",
    "CLASSIFIER_VERSION",
    "CONFLICT_MARGIN",
    "CONFLICT_SCORE_THRESHOLD",
    "CORE_DIVIDEND",
    "KNOWN_BUCKETS",
    "MANAGER_SCANNER_POLICY_VERSION",
    "NEWS_MOMENTUM",
    "REVIEW_THRESHOLD",
    "SCANNER_HINT_POLICY_VERSION",
    "StrategyBucketClassification",
    "UNASSIGNED",
    "VALUE_REBOUND",
    "classify_candidate_strategy_bucket",
]
