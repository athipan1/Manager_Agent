from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .analysis_evidence import build_analysis_evidence_summary


CORE_DIVIDEND = "core_dividend"
VALUE_REBOUND = "value_rebound"
NEWS_MOMENTUM = "news_momentum"
UNASSIGNED = "unassigned"
KNOWN_BUCKETS = {CORE_DIVIDEND, VALUE_REBOUND, NEWS_MOMENTUM}

CLASSIFIER_VERSION = "manager-strategy-bucket-v3"
AUTO_CLASSIFY_THRESHOLD = 0.70
REVIEW_THRESHOLD = 0.50
CONFLICT_SCORE_THRESHOLD = 0.65
CONFLICT_MARGIN = 0.10


@dataclass(frozen=True)
class StrategyBucketClassification:
    bucket: str
    confidence: float
    reasons: Tuple[str, ...]
    classifier_version: str = CLASSIFIER_VERSION
    status: str = "unassigned"
    proposed_bucket: Optional[str] = None
    source: str = "manager_classifier"
    conflict_buckets: Tuple[str, ...] = ()
    evidence_gate_passed: bool = True
    evidence_summary: Mapping[str, Any] = field(default_factory=dict)

    @property
    def allows_new_entry(self) -> bool:
        return (
            self.status == "classified"
            and self.bucket in KNOWN_BUCKETS
            and self.confidence >= AUTO_CLASSIFY_THRESHOLD
            and self.evidence_gate_passed
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "bucket": self.bucket,
            "confidence": round(float(self.confidence), 4),
            "reasons": list(self.reasons),
            "classifier_version": self.classifier_version,
            "status": self.status,
            "proposed_bucket": self.proposed_bucket,
            "source": self.source,
            "conflict_buckets": list(self.conflict_buckets),
            "evidence_gate_passed": self.evidence_gate_passed,
            "evidence_summary": dict(self.evidence_summary),
            "allows_new_entry": self.allows_new_entry,
        }


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _score01(value: Any) -> float:
    score = _clamp_confidence(value)
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return score
    if abs(raw) > 1.0:
        return _clamp_confidence(raw / 100.0)
    return score


def _ratio_decimal(value: Any) -> Decimal:
    number = _decimal(value)
    if abs(number) > Decimal("1"):
        number = number / Decimal("100")
    return number


def _mapping(value: Any) -> Mapping[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return value if isinstance(value, Mapping) else {}


def _analysis_details(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(analysis.get("details") or {})


def _fundamental_scores(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    details = _analysis_details(analysis)
    return _mapping(
        details.get("fundamental_analysis")
        or details.get("fundamental")
        or {}
    )


def _scanner_candidate(item: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(item.get("scanner_candidate") or {})


def _scanner_metadata(item: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_scanner_candidate(item).get("metadata") or {})


def _raw_scores(item: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_scanner_candidate(item).get("raw_scores") or {})


def _nested_get(
    mapping: Mapping[str, Any],
    path: Iterable[str],
    default: Any = None,
) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return default if current is None else current


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _normalize_bucket(value: Any) -> Optional[str]:
    bucket = str(value or "").strip().lower()
    return bucket if bucket in KNOWN_BUCKETS else None


def _add_evidence(
    scores: Dict[str, float],
    reasons: Dict[str, list[str]],
    bucket: str,
    confidence: float,
    reason: str,
) -> None:
    confidence = _clamp_confidence(confidence)
    previous = scores.get(bucket, 0.0)
    if previous:
        confidence = min(0.98, max(previous, confidence) + 0.04)
    scores[bucket] = max(previous, confidence)
    reasons.setdefault(bucket, []).append(reason)


def _invalid_scanner_hint(metadata: Mapping[str, Any]) -> Optional[str]:
    raw_primary = metadata.get("primary_strategy_bucket_hint")
    if raw_primary in (None, ""):
        return None
    return None if _normalize_bucket(raw_primary) else str(raw_primary)


def _scanner_evidence(
    scanner_source: Mapping[str, Any],
    metadata: Mapping[str, Any],
    scores: Dict[str, float],
    reasons: Dict[str, list[str]],
) -> None:
    primary = _normalize_bucket(
        scanner_source.get("primary_hint")
        or metadata.get("primary_strategy_bucket_hint")
    )
    raw_hint_scores = _mapping(
        scanner_source.get("bucket_scores")
        or metadata.get("bucket_hint_scores")
        or {}
    )
    hint_scores = {
        bucket: _clamp_confidence(score)
        for raw_bucket, score in raw_hint_scores.items()
        if (bucket := _normalize_bucket(raw_bucket))
    }
    versioned = bool(scanner_source.get("versioned"))

    if primary:
        primary_confidence = hint_scores.get(primary)
        if primary_confidence is None:
            primary_confidence = _clamp_confidence(
                scanner_source.get("primary_confidence")
                or metadata.get("primary_strategy_bucket_confidence")
                or metadata.get("strategy_bucket_confidence"),
                default=0.75,
            )
        if versioned:
            primary_confidence = min(primary_confidence, 0.68)
        _add_evidence(
            scores,
            reasons,
            primary,
            primary_confidence,
            f"scanner_primary_hint:{primary}",
        )

    raw_hints = metadata.get("strategy_bucket_hints") or []
    if isinstance(raw_hints, (list, tuple, set)):
        for raw_hint in raw_hints:
            bucket = _normalize_bucket(raw_hint)
            if not bucket or bucket == primary:
                continue
            confidence = hint_scores.get(bucket, 0.55)
            if versioned:
                confidence = min(confidence, 0.58)
            _add_evidence(
                scores,
                reasons,
                bucket,
                confidence,
                f"scanner_secondary_hint:{bucket}",
            )

    for bucket, confidence in hint_scores.items():
        if bucket == primary:
            continue
        if versioned:
            confidence = min(confidence, 0.58)
        _add_evidence(
            scores,
            reasons,
            bucket,
            confidence,
            f"scanner_bucket_score:{bucket}={confidence:.2f}",
        )


def _source_scale(summary: Mapping[str, Any], source_name: str) -> float:
    source = _mapping(
        _mapping(summary.get("sources")).get(source_name)
    )
    status = str(source.get("status") or "")
    if status == "partial":
        return 0.85
    if status == "insufficient":
        return 0.0
    return 1.0


def _evidence_gate_failure(
    summary: Mapping[str, Any],
) -> Optional[StrategyBucketClassification]:
    if not summary.get("gate_required"):
        return None

    issues = tuple(str(value) for value in summary.get("blocking_issues") or [])
    conflicts = tuple(
        str(value) for value in summary.get("source_conflicts") or []
    )
    if not issues and not conflicts:
        return None

    invalid_markers = (
        "unsupported_",
        "_authority_",
        "_must_require_",
        "_must_not_assign_",
        "invalid_",
    )
    status = (
        "invalid"
        if any(any(marker in issue for marker in invalid_markers) for issue in issues)
        else "conflict"
        if conflicts
        else "evidence_insufficient"
    )
    reasons = (
        ("analysis_evidence_gate_failed",)
        + issues
        + conflicts
    )
    return StrategyBucketClassification(
        bucket=UNASSIGNED,
        confidence=0.0,
        reasons=reasons,
        status=status,
        proposed_bucket=None,
        source="analysis_evidence_contract",
        evidence_gate_passed=False,
        evidence_summary=summary,
    )


def classify_candidate_strategy_bucket(
    item: Mapping[str, Any],
) -> StrategyBucketClassification:
    item = _mapping(item)
    analysis = _mapping(item.get("analysis") or {})
    metadata = _scanner_metadata(item)
    legacy_raw_scores = _raw_scores(item)
    legacy_fundamental = _fundamental_scores(analysis)
    evidence_summary = build_analysis_evidence_summary(item)

    gate_failure = _evidence_gate_failure(evidence_summary)
    if gate_failure:
        return gate_failure

    invalid_hint = _invalid_scanner_hint(metadata)
    if invalid_hint:
        return StrategyBucketClassification(
            bucket=UNASSIGNED,
            confidence=0.0,
            reasons=(f"invalid_scanner_bucket_hint:{invalid_hint}",),
            status="invalid",
            proposed_bucket=None,
            source="scanner_contract",
            evidence_gate_passed=False,
            evidence_summary=evidence_summary,
        )

    scores: Dict[str, float] = {}
    reasons: Dict[str, list[str]] = {}
    scanner_source = _mapping(
        _mapping(evidence_summary.get("sources")).get("scanner")
    )
    _scanner_evidence(scanner_source, metadata, scores, reasons)

    score_breakdown = _mapping(item.get("score_breakdown") or {})
    opportunity_score = _decimal(
        score_breakdown.get("final_opportunity_score")
    )

    tags = item.get("tags") or metadata.get("tags") or []
    tag_text = (
        " ".join(str(tag).lower() for tag in tags)
        if isinstance(tags, list)
        else str(tags).lower()
    )

    classification_inputs = _mapping(
        evidence_summary.get("classification_inputs")
    )
    fundamental_inputs = _mapping(
        classification_inputs.get("fundamental")
    )
    technical_inputs = _mapping(
        classification_inputs.get("technical")
    )

    sector = str(
        _first_value(
            metadata.get("sector"),
            fundamental_inputs.get("sector"),
            legacy_fundamental.get("sector"),
        )
        or ""
    ).strip().lower()

    dividend_yield = _ratio_decimal(
        _first_value(
            fundamental_inputs.get("dividend_yield"),
            legacy_raw_scores.get("dividend_yield"),
            legacy_fundamental.get("dividend_yield"),
            _nested_get(
                legacy_fundamental,
                ["metrics", "dividend_yield"],
            ),
        )
    )
    quality_score = _score01(
        _first_value(
            fundamental_inputs.get("quality_score"),
            legacy_raw_scores.get("quality_score"),
            legacy_fundamental.get("quality_score"),
        )
    )
    valuation_score = _score01(
        _first_value(
            fundamental_inputs.get("valuation_score"),
            legacy_raw_scores.get("valuation_score"),
            legacy_fundamental.get("valuation_score"),
        )
    )
    growth_score = _score01(
        _first_value(
            fundamental_inputs.get("growth_score"),
            legacy_raw_scores.get("growth_score"),
            legacy_fundamental.get("growth_score"),
        )
    )
    pe_ratio = _decimal(
        _first_value(
            fundamental_inputs.get("pe_ratio"),
            legacy_raw_scores.get("pe_ratio"),
            legacy_fundamental.get("pe_ratio"),
        ),
        Decimal("999"),
    )
    pb_ratio = _decimal(
        _first_value(
            fundamental_inputs.get("pb_ratio"),
            legacy_raw_scores.get("pb_ratio"),
            legacy_fundamental.get("pb_ratio"),
        ),
        Decimal("999"),
    )
    free_cash_flow = _decimal(
        _first_value(
            fundamental_inputs.get("free_cash_flow"),
            legacy_raw_scores.get("free_cash_flow"),
        )
    )
    debt_to_equity = _ratio_decimal(
        _first_value(
            fundamental_inputs.get("debt_to_equity"),
            legacy_raw_scores.get("debt_to_equity"),
        )
    )

    technical_score = _score01(
        technical_inputs.get("technical_score")
    )
    momentum_score = _score01(
        technical_inputs.get("momentum_score")
    )
    trend_score = _score01(technical_inputs.get("trend_score"))
    indicator_score = _score01(
        technical_inputs.get("indicator_score")
    )
    technical_vote_score = _score01(
        technical_inputs.get("technical_vote_score")
    )
    breakout_ratio = _decimal(
        technical_inputs.get("breakout_ratio")
    )

    fundamental_scale = _source_scale(
        evidence_summary,
        "fundamental",
    )
    technical_scale = _source_scale(
        evidence_summary,
        "technical",
    )
    technical_provenance = _mapping(
        _mapping(
            _mapping(evidence_summary.get("sources")).get("technical")
        ).get("provenance")
    )
    walk_forward_passed = technical_provenance.get(
        "walk_forward_passed"
    )
    if walk_forward_passed is False:
        technical_scale *= 0.70

    tag_rules = {
        NEWS_MOMENTUM: (
            "news",
            "catalyst",
            "momentum",
            "volume",
            "breakout",
            "trend",
        ),
        VALUE_REBOUND: (
            "value",
            "cheap",
            "undervalued",
            "rebound",
            "discount",
            "valuation",
        ),
        CORE_DIVIDEND: (
            "dividend",
            "quality",
            "defensive",
            "blue-chip",
            "stable",
            "cash-flow",
        ),
    }
    for bucket, hints in tag_rules.items():
        matched = sorted({hint for hint in hints if hint in tag_text})
        if matched:
            _add_evidence(
                scores,
                reasons,
                bucket,
                0.82,
                f"tag_evidence:{','.join(matched)}",
            )

    if dividend_yield > Decimal("0"):
        _add_evidence(
            scores,
            reasons,
            CORE_DIVIDEND,
            0.80 * fundamental_scale,
            f"dividend_yield:{dividend_yield}",
        )
    if sector in {
        "utilities",
        "consumer defensive",
        "healthcare",
        "financial services",
    }:
        _add_evidence(
            scores,
            reasons,
            CORE_DIVIDEND,
            0.72 * fundamental_scale,
            f"defensive_sector:{sector}",
        )
    if quality_score >= 0.70 and opportunity_score >= Decimal("0.55"):
        _add_evidence(
            scores,
            reasons,
            CORE_DIVIDEND,
            0.74 * fundamental_scale,
            f"quality_score:{quality_score:.2f}",
        )
    if (
        quality_score >= 0.65
        and free_cash_flow > Decimal("0")
        and debt_to_equity <= Decimal("1")
    ):
        _add_evidence(
            scores,
            reasons,
            CORE_DIVIDEND,
            0.76 * fundamental_scale,
            "quality_cashflow_low_debt",
        )

    if pe_ratio > Decimal("0") and pe_ratio <= Decimal("15"):
        _add_evidence(
            scores,
            reasons,
            VALUE_REBOUND,
            0.76 * fundamental_scale,
            f"low_pe_ratio:{pe_ratio}",
        )
    if pb_ratio > Decimal("0") and pb_ratio <= Decimal("1.5"):
        _add_evidence(
            scores,
            reasons,
            VALUE_REBOUND,
            0.76 * fundamental_scale,
            f"low_pb_ratio:{pb_ratio}",
        )
    if valuation_score >= 0.70:
        _add_evidence(
            scores,
            reasons,
            VALUE_REBOUND,
            0.72 * fundamental_scale,
            f"valuation_score:{valuation_score:.2f}",
        )

    growth_confidence = 0.72
    if walk_forward_passed is False:
        growth_confidence = 0.66
    if growth_score >= 0.70 and opportunity_score >= Decimal("0.62"):
        _add_evidence(
            scores,
            reasons,
            NEWS_MOMENTUM,
            growth_confidence * fundamental_scale,
            f"growth_score:{growth_score:.2f}",
        )

    technical_strength = max(
        technical_score,
        momentum_score,
        trend_score,
        indicator_score,
        technical_vote_score,
    )
    if momentum_score >= 0.70 and trend_score >= 0.65:
        _add_evidence(
            scores,
            reasons,
            NEWS_MOMENTUM,
            0.68 * technical_scale,
            (
                "technical_momentum_trend:"
                f"momentum={momentum_score:.2f},trend={trend_score:.2f}"
            ),
        )
    if breakout_ratio >= Decimal("0.97") and technical_vote_score >= 0.65:
        _add_evidence(
            scores,
            reasons,
            NEWS_MOMENTUM,
            0.68 * technical_scale,
            (
                "breakout_confirmation:"
                f"ratio={breakout_ratio},vote={technical_vote_score:.2f}"
            ),
        )
    if growth_score >= 0.65 and technical_strength >= 0.65:
        _add_evidence(
            scores,
            reasons,
            NEWS_MOMENTUM,
            0.82 * min(fundamental_scale, technical_scale),
            (
                "growth_technical_corroboration:"
                f"growth={growth_score:.2f},technical={technical_strength:.2f}"
            ),
        )

    if not scores:
        return StrategyBucketClassification(
            bucket=UNASSIGNED,
            confidence=0.0,
            reasons=("insufficient_bucket_evidence",),
            status="unassigned",
            proposed_bucket=None,
            evidence_gate_passed=bool(
                evidence_summary.get("gate_passed", True)
            ),
            evidence_summary=evidence_summary,
        )

    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    proposed_bucket, top_score = ranked[0]
    second_bucket, second_score = (
        ranked[1] if len(ranked) > 1 else (None, 0.0)
    )

    if (
        second_bucket
        and top_score >= CONFLICT_SCORE_THRESHOLD
        and second_score >= CONFLICT_SCORE_THRESHOLD
        and (top_score - second_score) < CONFLICT_MARGIN
    ):
        conflict_buckets = tuple(
            bucket
            for bucket, score in ranked
            if score >= CONFLICT_SCORE_THRESHOLD
        )
        conflict_reasons = tuple(
            reason
            for bucket in conflict_buckets
            for reason in reasons.get(bucket, [])
        )
        return StrategyBucketClassification(
            bucket=UNASSIGNED,
            confidence=top_score,
            reasons=("conflicting_bucket_evidence", *conflict_reasons),
            status="conflict",
            proposed_bucket=proposed_bucket,
            conflict_buckets=conflict_buckets,
            evidence_gate_passed=True,
            evidence_summary=evidence_summary,
        )

    top_reasons = tuple(reasons.get(proposed_bucket, []))
    if top_score >= AUTO_CLASSIFY_THRESHOLD:
        return StrategyBucketClassification(
            bucket=proposed_bucket,
            confidence=top_score,
            reasons=top_reasons,
            status="classified",
            proposed_bucket=proposed_bucket,
            evidence_gate_passed=True,
            evidence_summary=evidence_summary,
        )
    if top_score >= REVIEW_THRESHOLD:
        return StrategyBucketClassification(
            bucket=UNASSIGNED,
            confidence=top_score,
            reasons=("classification_requires_review", *top_reasons),
            status="review",
            proposed_bucket=proposed_bucket,
            evidence_gate_passed=True,
            evidence_summary=evidence_summary,
        )
    return StrategyBucketClassification(
        bucket=UNASSIGNED,
        confidence=top_score,
        reasons=(
            "classification_confidence_below_review_threshold",
            *top_reasons,
        ),
        status="unassigned",
        proposed_bucket=proposed_bucket,
        evidence_gate_passed=True,
        evidence_summary=evidence_summary,
    )
