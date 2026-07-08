from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple


CORE_DIVIDEND = "core_dividend"
VALUE_REBOUND = "value_rebound"
NEWS_MOMENTUM = "news_momentum"
UNASSIGNED = "unassigned"
KNOWN_BUCKETS = {CORE_DIVIDEND, VALUE_REBOUND, NEWS_MOMENTUM}

CLASSIFIER_VERSION = "manager-strategy-bucket-v2"
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

    @property
    def allows_new_entry(self) -> bool:
        return (
            self.status == "classified"
            and self.bucket in KNOWN_BUCKETS
            and self.confidence >= AUTO_CLASSIFY_THRESHOLD
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


def _mapping(value: Any) -> Mapping[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return value if isinstance(value, Mapping) else {}


def _analysis_details(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(analysis.get("details") or {})


def _fundamental_scores(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    details = _analysis_details(analysis)
    return _mapping(details.get("fundamental_analysis") or details.get("fundamental") or {})


def _scanner_candidate(item: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(item.get("scanner_candidate") or {})


def _scanner_metadata(item: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_scanner_candidate(item).get("metadata") or {})


def _raw_scores(item: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_scanner_candidate(item).get("raw_scores") or {})


def _nested_get(mapping: Mapping[str, Any], path: Iterable[str], default: Any = None) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return default if current is None else current


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
    metadata: Mapping[str, Any],
    scores: Dict[str, float],
    reasons: Dict[str, list[str]],
) -> None:
    primary = _normalize_bucket(metadata.get("primary_strategy_bucket_hint"))
    raw_hint_scores = _mapping(metadata.get("bucket_hint_scores") or {})
    hint_scores = {
        bucket: _clamp_confidence(score)
        for raw_bucket, score in raw_hint_scores.items()
        if (bucket := _normalize_bucket(raw_bucket))
    }

    if primary:
        primary_confidence = hint_scores.get(primary)
        if primary_confidence is None:
            primary_confidence = _clamp_confidence(
                metadata.get("primary_strategy_bucket_confidence")
                or metadata.get("strategy_bucket_confidence"),
                default=0.75,
            )
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
        _add_evidence(
            scores,
            reasons,
            bucket,
            confidence,
            f"scanner_bucket_score:{bucket}={confidence:.2f}",
        )


def classify_candidate_strategy_bucket(item: Mapping[str, Any]) -> StrategyBucketClassification:
    item = _mapping(item)
    analysis = _mapping(item.get("analysis") or {})
    metadata = _scanner_metadata(item)
    raw_scores = _raw_scores(item)
    fundamental = _fundamental_scores(analysis)

    invalid_hint = _invalid_scanner_hint(metadata)
    if invalid_hint:
        return StrategyBucketClassification(
            bucket=UNASSIGNED,
            confidence=0.0,
            reasons=(f"invalid_scanner_bucket_hint:{invalid_hint}",),
            status="invalid",
            proposed_bucket=None,
            source="scanner_contract",
        )

    scores: Dict[str, float] = {}
    reasons: Dict[str, list[str]] = {}
    _scanner_evidence(metadata, scores, reasons)

    score_breakdown = _mapping(item.get("score_breakdown") or {})
    opportunity_score = _decimal(score_breakdown.get("final_opportunity_score"))

    tags = item.get("tags") or metadata.get("tags") or []
    tag_text = " ".join(str(tag).lower() for tag in tags) if isinstance(tags, list) else str(tags).lower()
    sector = str(metadata.get("sector") or fundamental.get("sector") or "").strip().lower()

    dividend_yield = _decimal(
        raw_scores.get("dividend_yield")
        or fundamental.get("dividend_yield")
        or _nested_get(fundamental, ["metrics", "dividend_yield"])
    )
    quality_score = _decimal(raw_scores.get("quality_score") or fundamental.get("quality_score"))
    pe_ratio = _decimal(raw_scores.get("pe_ratio") or fundamental.get("pe_ratio"), Decimal("999"))
    pb_ratio = _decimal(raw_scores.get("pb_ratio") or fundamental.get("pb_ratio"), Decimal("999"))
    growth_score = _decimal(raw_scores.get("growth_score") or fundamental.get("growth_score"))

    tag_rules = {
        NEWS_MOMENTUM: ("news", "catalyst", "momentum", "volume", "breakout", "trend"),
        VALUE_REBOUND: ("value", "cheap", "undervalued", "rebound", "discount", "valuation"),
        CORE_DIVIDEND: ("dividend", "quality", "defensive", "blue-chip", "stable", "cash-flow"),
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
        _add_evidence(scores, reasons, CORE_DIVIDEND, 0.80, f"dividend_yield:{dividend_yield}")
    if sector in {"utilities", "consumer defensive", "healthcare", "financial services"}:
        _add_evidence(scores, reasons, CORE_DIVIDEND, 0.72, f"defensive_sector:{sector}")
    if quality_score >= Decimal("70") and opportunity_score >= Decimal("0.55"):
        _add_evidence(scores, reasons, CORE_DIVIDEND, 0.74, f"quality_score:{quality_score}")
    if pe_ratio > Decimal("0") and pe_ratio <= Decimal("15"):
        _add_evidence(scores, reasons, VALUE_REBOUND, 0.76, f"low_pe_ratio:{pe_ratio}")
    if pb_ratio > Decimal("0") and pb_ratio <= Decimal("1.5"):
        _add_evidence(scores, reasons, VALUE_REBOUND, 0.76, f"low_pb_ratio:{pb_ratio}")
    if growth_score >= Decimal("70") and opportunity_score >= Decimal("0.62"):
        _add_evidence(scores, reasons, NEWS_MOMENTUM, 0.72, f"growth_score:{growth_score}")

    if not scores:
        return StrategyBucketClassification(
            bucket=UNASSIGNED,
            confidence=0.0,
            reasons=("insufficient_bucket_evidence",),
            status="unassigned",
            proposed_bucket=None,
        )

    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    proposed_bucket, top_score = ranked[0]
    second_bucket, second_score = ranked[1] if len(ranked) > 1 else (None, 0.0)

    if (
        second_bucket
        and top_score >= CONFLICT_SCORE_THRESHOLD
        and second_score >= CONFLICT_SCORE_THRESHOLD
        and (top_score - second_score) < CONFLICT_MARGIN
    ):
        conflict_buckets = tuple(bucket for bucket, score in ranked if score >= CONFLICT_SCORE_THRESHOLD)
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
        )

    top_reasons = tuple(reasons.get(proposed_bucket, []))
    if top_score >= AUTO_CLASSIFY_THRESHOLD:
        return StrategyBucketClassification(
            bucket=proposed_bucket,
            confidence=top_score,
            reasons=top_reasons,
            status="classified",
            proposed_bucket=proposed_bucket,
        )
    if top_score >= REVIEW_THRESHOLD:
        return StrategyBucketClassification(
            bucket=UNASSIGNED,
            confidence=top_score,
            reasons=("classification_requires_review", *top_reasons),
            status="review",
            proposed_bucket=proposed_bucket,
        )
    return StrategyBucketClassification(
        bucket=UNASSIGNED,
        confidence=top_score,
        reasons=("classification_confidence_below_review_threshold", *top_reasons),
        status="unassigned",
        proposed_bucket=proposed_bucket,
    )
