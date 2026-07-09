from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from .analysis_evidence import build_analysis_evidence_summary
from .strategy_bucket_classifier import (
    AUTO_CLASSIFY_THRESHOLD,
    CLASSIFIER_VERSION,
    CONFLICT_MARGIN,
    CONFLICT_SCORE_THRESHOLD,
    CORE_DIVIDEND,
    KNOWN_BUCKETS,
    NEWS_MOMENTUM,
    REVIEW_THRESHOLD,
    StrategyBucketClassification,
    UNASSIGNED,
    VALUE_REBOUND,
    classify_candidate_strategy_bucket as _classify_candidate_strategy_bucket,
)


SCANNER_HINT_CONTRACT_VERSION = "scanner-bucket-hints-v2"
SCANNER_HINT_POLICY_VERSION = "scanner-bucket-hint-policy-v3"
MANAGER_SCANNER_POLICY_VERSION = "manager-scanner-policy-v1"

_MACHINE_TAG_PREFIXES = (
    "bucket-hint:",
    "bucket-candidate:",
    "bucket-hint-status:",
    "strategy-bucket:",
)

_SUPPORTING_TAGS = {
    NEWS_MOMENTUM: {
        "news",
        "catalyst",
        "momentum",
        "volume",
        "breakout",
        "trend",
    },
    VALUE_REBOUND: {
        "value",
        "cheap",
        "undervalued",
        "rebound",
        "discount",
        "valuation",
    },
    CORE_DIVIDEND: {
        "dividend",
        "defensive",
        "blue-chip",
    },
}

_DEFENSIVE_SECTORS = {
    "utilities",
    "consumer defensive",
    "consumer staples",
    "healthcare",
}


def _mapping(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _normalize_bucket(value: Any) -> Optional[str]:
    bucket = str(value or "").strip().lower()
    return bucket if bucket in KNOWN_BUCKETS else None


def _score01(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if abs(score) > 1.0:
        score /= 100.0
    return max(0.0, min(1.0, score))


def _iter_tags(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def _is_machine_tag(tag: str) -> bool:
    normalized = tag.strip().lower()
    return normalized.startswith(_MACHINE_TAG_PREFIXES)


def _scanner_parts(item: Mapping[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    candidate = _mapping(item.get("scanner_candidate"))
    metadata = _mapping(candidate.get("metadata"))
    bucket_hint = _mapping(candidate.get("bucket_hint"))
    return candidate, metadata, bucket_hint


def _scanner_policy_context(item: Mapping[str, Any]) -> Dict[str, Any]:
    candidate, metadata, bucket_hint = _scanner_parts(item)
    merged = {**metadata, **bucket_hint}
    policy_version = str(
        merged.get("bucket_hint_policy_version") or ""
    ).strip()
    status = str(merged.get("bucket_hint_status") or "").strip().lower()
    primary = _normalize_bucket(
        merged.get("primary_strategy_bucket_hint")
    )
    bucket_scores = {
        bucket: _score01(score)
        for raw_bucket, score in _mapping(
            merged.get("bucket_hint_scores")
        ).items()
        if (bucket := _normalize_bucket(raw_bucket))
    }
    return {
        "candidate": candidate,
        "metadata": metadata,
        "bucket_hint": bucket_hint,
        "contract_version": str(
            merged.get("bucket_hint_version") or ""
        ).strip(),
        "policy_version": policy_version,
        "status": status,
        "primary": primary,
        "bucket_scores": bucket_scores,
        "defining_evidence": _mapping(
            merged.get("bucket_hint_defining_evidence")
        ),
        "supporting_evidence": _mapping(
            merged.get("bucket_hint_supporting_evidence")
        ),
        "dominance_rule": merged.get("bucket_hint_dominance_rule"),
    }


def _recursive_scrub_financial_services(value: Any) -> bool:
    changed = False
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key == "sector" and str(child or "").strip().lower() == "financial services":
                value[key] = ""
                changed = True
            elif _recursive_scrub_financial_services(child):
                changed = True
    elif isinstance(value, list):
        for child in value:
            if _recursive_scrub_financial_services(child):
                changed = True
    return changed


def _recursive_set_metric(value: Any, metric: str, replacement: Any) -> int:
    changed = 0
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key == metric:
                value[key] = replacement
                changed += 1
            else:
                changed += _recursive_set_metric(child, metric, replacement)
    elif isinstance(value, list):
        for child in value:
            changed += _recursive_set_metric(child, metric, replacement)
    return changed


def _recursive_metric_values(value: Any, metric: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == metric:
                values.append(child)
            values.extend(_recursive_metric_values(child, metric))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            values.extend(_recursive_metric_values(child, metric))
    return values


def _first_numeric(values: Iterable[Any]) -> float:
    for value in values:
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _max_score(values: Iterable[Any]) -> float:
    return max((_score01(value) for value in values), default=0.0)


def _has_core_identity(item: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    if (
        policy.get("status") == "suggested"
        and policy.get("primary") == CORE_DIVIDEND
    ):
        return True

    core_defining = policy.get("defining_evidence") or {}
    if isinstance(core_defining, Mapping):
        for reason in core_defining.get(CORE_DIVIDEND) or []:
            text = str(reason).lower()
            if text.startswith("dividend_yield:") or text.startswith(
                "defensive_or_income_sector:"
            ):
                return True

    dividend_values = _recursive_metric_values(item, "dividend_yield")
    if any(_score01(value) > 0.0 for value in dividend_values):
        return True

    sectors = {
        str(value or "").strip().lower()
        for value in _recursive_metric_values(item, "sector")
    }
    return bool(sectors & _DEFENSIVE_SECTORS)


def _technical_strength(item: Mapping[str, Any]) -> float:
    metric_names = (
        "technical_score",
        "momentum_score",
        "trend_score",
        "indicator_score",
        "technical_vote_score",
    )
    return max(
        (
            _max_score(_recursive_metric_values(item, metric))
            for metric in metric_names
        ),
        default=0.0,
    )


def _human_tags(item: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    candidate, metadata, _ = _scanner_parts(item)
    raw_tags = [
        *_iter_tags(item.get("tags")),
        *_iter_tags(candidate.get("tags")),
        *_iter_tags(metadata.get("tags")),
    ]
    human: list[str] = []
    ignored: list[str] = []
    for tag in raw_tags:
        if _is_machine_tag(tag):
            ignored.append(tag)
        elif tag not in human:
            human.append(tag)
    return human, ignored


def _apply_policy_v3_to_hint(container: Dict[str, Any], policy: Mapping[str, Any]) -> None:
    if not container:
        return
    status = str(policy.get("status") or "")
    primary = policy.get("primary")
    original_scores = policy.get("bucket_scores") or {}

    adjusted_scores: Dict[str, float] = {}
    if status == "suggested" and primary:
        for bucket in KNOWN_BUCKETS:
            score = _score01(original_scores.get(bucket))
            adjusted_scores[bucket] = min(
                score,
                0.68 if bucket == primary else 0.48,
            )
        container["primary_strategy_bucket_hint"] = primary
        container["primary_strategy_bucket_confidence"] = adjusted_scores[
            primary
        ]
        container["strategy_bucket_hints"] = [primary]
    elif status == "review":
        adjusted_scores = {
            bucket: min(_score01(original_scores.get(bucket)), 0.48)
            for bucket in KNOWN_BUCKETS
        }
        container["primary_strategy_bucket_hint"] = None
        container["primary_strategy_bucket_confidence"] = None
        container["strategy_bucket_hints"] = []
    elif status == "insufficient_evidence":
        adjusted_scores = {bucket: 0.0 for bucket in KNOWN_BUCKETS}
        container["primary_strategy_bucket_hint"] = None
        container["primary_strategy_bucket_confidence"] = None
        container["strategy_bucket_hints"] = []
    else:
        return

    container["bucket_hint_scores"] = adjusted_scores
    container["strategy_bucket_confidence"] = max(
        adjusted_scores.values(),
        default=0.0,
    )


def _sanitized_item(item: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    sanitized = deepcopy(dict(item))
    candidate = _mapping(sanitized.get("scanner_candidate"))
    metadata = _mapping(candidate.get("metadata"))
    bucket_hint = _mapping(candidate.get("bucket_hint"))

    human_tags, ignored_tags = _human_tags(item)
    sanitized["tags"] = []
    candidate["tags"] = []
    metadata["tags"] = []

    policy_v3 = (
        policy.get("contract_version") == SCANNER_HINT_CONTRACT_VERSION
        and policy.get("policy_version") == SCANNER_HINT_POLICY_VERSION
    )
    if policy_v3:
        _apply_policy_v3_to_hint(metadata, policy)
        _apply_policy_v3_to_hint(bucket_hint, policy)

    candidate["metadata"] = metadata
    candidate["bucket_hint"] = bucket_hint
    sanitized["scanner_candidate"] = candidate

    financial_sector_scrubbed = _recursive_scrub_financial_services(sanitized)

    core_identity = _has_core_identity(item, policy)
    neutralized_quality_metrics = 0
    if not core_identity:
        neutralized_quality_metrics = _recursive_set_metric(
            sanitized,
            "quality_score",
            0.0,
        )

    technical_strength = _technical_strength(item)
    has_news_tag = any(
        any(token in tag.lower() for token in _SUPPORTING_TAGS[NEWS_MOMENTUM])
        for tag in human_tags
    )
    growth_neutralized = False
    if (
        policy_v3
        and policy.get("primary") != NEWS_MOMENTUM
        and technical_strength < 0.65
        and not has_news_tag
    ):
        growth_neutralized = (
            _recursive_set_metric(sanitized, "growth_score", 0.0) > 0
        )

    return sanitized, {
        "human_tags": human_tags,
        "ignored_machine_tags": ignored_tags,
        "financial_sector_scrubbed": financial_sector_scrubbed,
        "core_identity_present": core_identity,
        "neutralized_quality_metrics": neutralized_quality_metrics,
        "technical_strength": technical_strength,
        "growth_neutralized": growth_neutralized,
        "policy_v3": policy_v3,
    }


def _matching_supporting_tags(tags: Iterable[str], bucket: Optional[str]) -> list[str]:
    if not bucket or bucket not in _SUPPORTING_TAGS:
        return []
    matched: set[str] = set()
    for tag in tags:
        normalized = tag.lower()
        for token in _SUPPORTING_TAGS[bucket]:
            if token in normalized:
                matched.add(token)
    return sorted(matched)


def _augmented_summary(
    item: Mapping[str, Any],
    policy: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> Dict[str, Any]:
    summary = build_analysis_evidence_summary(item)
    sources = _mapping(summary.get("sources"))
    scanner = _mapping(sources.get("scanner"))
    provenance = _mapping(scanner.get("provenance"))
    provenance.update(
        {
            "bucket_hint_policy_version": policy.get("policy_version"),
            "bucket_hint_defining_evidence": policy.get(
                "defining_evidence"
            )
            or {},
            "bucket_hint_supporting_evidence": policy.get(
                "supporting_evidence"
            )
            or {},
            "bucket_hint_dominance_rule": policy.get("dominance_rule"),
            "manager_scanner_policy_version": MANAGER_SCANNER_POLICY_VERSION,
            "generic_tags_supporting_only": True,
            "ignored_machine_tags": list(
                audit.get("ignored_machine_tags") or []
            ),
        }
    )
    scanner["provenance"] = provenance
    scanner["policy_version"] = policy.get("policy_version")
    sources["scanner"] = scanner
    summary["sources"] = sources

    classification_inputs = _mapping(summary.get("classification_inputs"))
    scanner_inputs = _mapping(classification_inputs.get("scanner"))
    scanner_inputs.update(
        {
            "policy_version": policy.get("policy_version"),
            "status": policy.get("status"),
            "dominance_rule": policy.get("dominance_rule"),
            "defining_evidence": policy.get("defining_evidence") or {},
            "supporting_evidence": policy.get("supporting_evidence") or {},
        }
    )
    classification_inputs["scanner"] = scanner_inputs
    summary["classification_inputs"] = classification_inputs
    summary["manager_scanner_policy_version"] = (
        MANAGER_SCANNER_POLICY_VERSION
    )
    return summary


def classify_candidate_strategy_bucket(
    item: Mapping[str, Any],
) -> StrategyBucketClassification:
    """Classify with Scanner policy-v3 compatibility and no tag double-counting."""
    original = _mapping(item)
    policy = _scanner_policy_context(original)
    sanitized, audit = _sanitized_item(original, policy)
    base = _classify_candidate_strategy_bucket(sanitized)
    summary = _augmented_summary(original, policy, audit)

    reasons = list(base.reasons)
    if audit.get("policy_v3"):
        reasons.append("scanner_policy_v3_consumed")
        if policy.get("status") == "review":
            reasons.append("scanner_review_is_advisory")
        elif policy.get("status") == "suggested" and policy.get("primary"):
            reasons.append(
                f"scanner_policy_primary:{policy.get('primary')}"
            )
        if policy.get("dominance_rule"):
            reasons.append(
                f"scanner_dominance_rule:{policy.get('dominance_rule')}"
            )
    if audit.get("ignored_machine_tags"):
        reasons.append("machine_bucket_tags_ignored")
    if audit.get("financial_sector_scrubbed"):
        reasons.append("financial_services_not_defensive_sector")
    if (
        not audit.get("core_identity_present")
        and audit.get("neutralized_quality_metrics")
    ):
        reasons.append("quality_core_requires_income_identity")
    if audit.get("growth_neutralized"):
        reasons.append("growth_only_momentum_requires_technical_corroboration")

    proposed = base.proposed_bucket or (
        base.bucket if base.bucket in KNOWN_BUCKETS else None
    )
    matching_tags = _matching_supporting_tags(
        audit.get("human_tags") or [],
        proposed,
    )
    confidence = base.confidence
    if matching_tags and base.status in {"classified", "review"}:
        confidence = min(0.98, confidence + 0.02)
        reasons.append(
            "supporting_tag_evidence:" + ",".join(matching_tags)
        )

    return StrategyBucketClassification(
        bucket=base.bucket,
        confidence=confidence,
        reasons=tuple(dict.fromkeys(str(reason) for reason in reasons)),
        classifier_version=base.classifier_version,
        status=base.status,
        proposed_bucket=base.proposed_bucket,
        source="manager_classifier_scanner_policy_v3",
        conflict_buckets=base.conflict_buckets,
        evidence_gate_passed=base.evidence_gate_passed,
        evidence_summary=summary,
    )


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
