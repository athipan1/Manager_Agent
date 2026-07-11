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


def _resolve_value_momentum_overlap(
    item: Mapping[str, Any],
    decision: StrategyBucketClassification,
) -> StrategyBucketClassification:
    """Keep a governed value identity when momentum evidence is only technical.

    Scanner policy v3 can explicitly select ``value_rebound`` through a dominance
    rule while strong trend/momentum metrics independently push the generic
    classifier toward ``news_momentum``. Technical strength is useful supporting
    evidence, but without a human news/catalyst identity it must not quarantine a
    deep-value candidate that Scanner already resolved deterministically.
    """
    if (
        decision.status != "conflict"
        or decision.proposed_bucket != VALUE_REBOUND
        or set(decision.conflict_buckets)
        != {VALUE_REBOUND, NEWS_MOMENTUM}
    ):
        return decision

    policy = _scanner_policy_context(item)
    reasons = tuple(str(reason) for reason in decision.reasons)
    value_dominance = (
        policy.get("status") == "suggested"
        and policy.get("primary") == VALUE_REBOUND
        and policy.get("dominance_rule")
        in {
            "deep_value_without_income_dominance",
            "value_rebound_dominates_growth_without_news",
        }
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
    explicit_news_identity = any(
        (
            reason.startswith("tag_evidence:")
            or reason.startswith("supporting_tag_evidence:")
        )
        and any(token in reason.lower() for token in ("news", "catalyst"))
        for reason in reasons
    ) or any(
        reason in {
            "scanner_primary_hint:news_momentum",
            "scanner_policy_primary:news_momentum",
        }
        for reason in reasons
    )

    if not value_dominance or not strong_value_reasons or explicit_news_identity:
        return decision

    supporting_momentum_reasons = tuple(
        reason
        for reason in reasons
        if reason.startswith("technical_momentum_trend:")
        or reason.startswith("breakout_confirmation:")
        or reason.startswith("growth_technical_corroboration:")
    )
    policy_reasons = tuple(
        reason
        for reason in reasons
        if reason.startswith("scanner_policy_")
        or reason.startswith("scanner_dominance_rule:")
        or reason.startswith("machine_")
        or reason.startswith("financial_services_")
        or reason.startswith("quality_core_")
    )
    return StrategyBucketClassification(
        bucket=VALUE_REBOUND,
        confidence=decision.confidence,
        reasons=tuple(
            dict.fromkeys(
                (
                    "value_policy_dominates_technical_momentum_only",
                    *strong_value_reasons,
                    *supporting_momentum_reasons,
                    *policy_reasons,
                )
            )
        ),
        classifier_version=decision.classifier_version,
        status="classified",
        proposed_bucket=VALUE_REBOUND,
        source="manager_scanner_policy_v3_value_momentum_resolution",
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
    decision = _resolve_sector_quality_value_overlap(decision)
    return _resolve_value_momentum_overlap(item, decision)


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
