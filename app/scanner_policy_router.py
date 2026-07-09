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
    return _classify_policy_v3(item)


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
