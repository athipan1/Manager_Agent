"""Fail-safe Scanner candidate data-quality policy for Manager_Agent.

Scanner_Agent v1.3 attaches ``scanner-data-bundle.v1`` to candidates. Manager
must validate that evidence before spending downstream Technical/Fundamental/Risk
capacity or allowing a candidate to approach execution.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .scanner_candidate_service import candidate_to_dict

SCANNER_DATA_BUNDLE_SCHEMA = "scanner-data-bundle.v1"
SCANNER_DATA_QUALITY_POLICY_VERSION = "scanner-data-quality-gate.v2"
DEFAULT_MIN_COVERAGE_RATIO = 0.80


def _to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def _finite_ratio(value: Any) -> Optional[float]:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(ratio):
        return None
    if ratio < 0 or ratio > 1:
        return None
    return ratio


def scanner_min_data_coverage() -> float:
    """Return the configured Scanner evidence threshold, clamped to [0, 1]."""

    raw = os.getenv("SCANNER_MIN_DATA_COVERAGE", str(DEFAULT_MIN_COVERAGE_RATIO))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_MIN_COVERAGE_RATIO
    if not math.isfinite(value):
        return DEFAULT_MIN_COVERAGE_RATIO
    return max(0.0, min(1.0, value))


def scanner_candidate_data_bundle(candidate: Any) -> Dict[str, Any]:
    """Locate Scanner's data bundle across current technical/fundamental shapes."""

    data = candidate_to_dict(candidate)
    metadata = _to_dict(data.get("metadata"))
    details = _to_dict(metadata.get("details"))

    for value in (
        data.get("data_bundle"),
        metadata.get("data_bundle"),
        details.get("data_bundle"),
    ):
        bundle = _to_dict(value)
        if bundle:
            return bundle
    return {}


def _statement_coverage_ratio(quality: Dict[str, Any]) -> Optional[float]:
    statements = _to_dict(quality.get("financial_statements"))
    available = statements.get("available_statements")
    missing = statements.get("missing_statements")
    if isinstance(available, list) and isinstance(missing, list):
        total = len(available) + len(missing)
        if total:
            return len(available) / total
    return None


def _evidence_coverage_ratio(candidate: Any) -> Optional[float]:
    data = candidate_to_dict(candidate)
    metadata = _to_dict(data.get("metadata"))
    raw_scores = _to_dict(data.get("raw_scores")) or _to_dict(metadata.get("raw_scores"))
    evidence = _to_dict(metadata.get("evidence_coverage"))
    for value in (
        raw_scores.get("evidence_coverage"),
        evidence.get("ratio"),
    ):
        ratio = _finite_ratio(value)
        if ratio is not None:
            return ratio
    return None


def _coverage_contract(
    candidate: Any,
    bundle: Dict[str, Any],
) -> Tuple[Optional[float], str, Dict[str, Any]]:
    """Resolve the correct pre-analysis coverage scope without relaxing its threshold.

    Technical Scanner candidates now expose ``data_quality.analysis`` containing
    only evidence required to justify downstream Technical/Fundamental work. The
    legacy full-enrichment ratio also includes sector/backtest/fundamental extras and
    remains diagnostic, but optional downstream enrichment must not masquerade as a
    Technical data gap. Fundamental discovery bundles keep the legacy evidence
    aggregation until they publish a dedicated scope.
    """

    quality = _to_dict(bundle.get("data_quality"))
    analysis_quality = _to_dict(quality.get("analysis"))
    analysis_ratio = _finite_ratio(analysis_quality.get("coverage_ratio"))
    if analysis_ratio is not None:
        return analysis_ratio, "analysis_ready", analysis_quality

    direct = _finite_ratio(quality.get("coverage_ratio"))
    if direct is not None:
        return direct, "legacy_full_enrichment", quality

    component_ratios: List[float] = []
    market_quality = _to_dict(quality.get("market"))
    if not market_quality:
        market_quality = _to_dict(_to_dict(bundle.get("market_snapshot")).get("data_quality"))
    market_ratio = _finite_ratio(market_quality.get("coverage_ratio"))
    if market_ratio is not None:
        component_ratios.append(market_ratio)

    statement_ratio = _statement_coverage_ratio(quality)
    if statement_ratio is not None:
        component_ratios.append(statement_ratio)

    evidence_ratio = _evidence_coverage_ratio(candidate)
    if evidence_ratio is not None:
        component_ratios.append(evidence_ratio)

    if component_ratios:
        return round(sum(component_ratios) / len(component_ratios), 4), "derived_fundamental", quality

    if str(quality.get("status") or "").lower() == "complete":
        return 1.0, "legacy_complete_status", quality
    return None, "unknown", quality


def scanner_candidate_coverage_ratio(candidate: Any, bundle: Dict[str, Any]) -> Optional[float]:
    """Return the coverage ratio appropriate for the pre-analysis gate."""

    ratio, _, _ = _coverage_contract(candidate, bundle)
    return ratio


def _review_result(
    *,
    symbol: str,
    reason_code: str,
    reason: str,
    schema_version: Optional[str],
    status: Optional[str],
    coverage_ratio: Optional[float],
    coverage_scope: str,
    threshold: float,
    quality: Optional[Dict[str, Any]] = None,
    scoped_quality: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    quality = quality or {}
    scoped_quality = scoped_quality or quality
    return {
        "symbol": symbol,
        "decision": "REVIEW",
        "allowed": False,
        "reason_code": reason_code,
        "reason": reason,
        "policy_version": SCANNER_DATA_QUALITY_POLICY_VERSION,
        "required_schema": SCANNER_DATA_BUNDLE_SCHEMA,
        "schema_version": schema_version,
        "status": status,
        "coverage_ratio": coverage_ratio,
        "coverage_scope": coverage_scope,
        "legacy_full_coverage_ratio": _finite_ratio(quality.get("coverage_ratio")),
        "min_coverage_ratio": threshold,
        "required_components": list(scoped_quality.get("required_components") or []),
        "missing_components": list(scoped_quality.get("missing_components") or []),
        "partial_components": list(scoped_quality.get("partial_components") or []),
        "market_missing_fields": list(quality.get("market_missing_fields") or []),
        "market_provider_errors": list(quality.get("market_provider_errors") or []),
    }


def evaluate_scanner_candidate_data_quality(
    candidate: Any,
    *,
    min_coverage_ratio: Optional[float] = None,
) -> Dict[str, Any]:
    """Classify a Scanner candidate as PASS or REVIEW before downstream agents."""

    data = candidate_to_dict(candidate)
    symbol = str(data.get("symbol") or "unknown").upper()
    threshold = (
        scanner_min_data_coverage()
        if min_coverage_ratio is None
        else max(0.0, min(1.0, float(min_coverage_ratio)))
    )
    bundle = scanner_candidate_data_bundle(candidate)
    if not bundle:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_DATA_BUNDLE_MISSING",
            reason="Scanner candidate has no scanner-data-bundle.v1 evidence.",
            schema_version=None,
            status=None,
            coverage_ratio=None,
            coverage_scope="unknown",
            threshold=threshold,
        )

    schema_version = str(bundle.get("schema_version") or "").strip() or None
    quality = _to_dict(bundle.get("data_quality"))
    status = str(quality.get("status") or "").strip().lower() or None
    coverage_ratio, coverage_scope, scoped_quality = _coverage_contract(candidate, bundle)

    if schema_version != SCANNER_DATA_BUNDLE_SCHEMA:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_DATA_BUNDLE_SCHEMA_UNSUPPORTED",
            reason=(
                "Scanner candidate data bundle schema is unsupported; "
                f"expected {SCANNER_DATA_BUNDLE_SCHEMA}."
            ),
            schema_version=schema_version,
            status=status,
            coverage_ratio=coverage_ratio,
            coverage_scope=coverage_scope,
            threshold=threshold,
            quality=quality,
            scoped_quality=scoped_quality,
        )

    scoped_status = str(scoped_quality.get("status") or status or "").strip().lower() or None
    if scoped_status not in {"complete", "partial"}:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_DATA_QUALITY_MISSING",
            reason="Scanner candidate data quality is missing or unusable.",
            schema_version=schema_version,
            status=scoped_status,
            coverage_ratio=coverage_ratio,
            coverage_scope=coverage_scope,
            threshold=threshold,
            quality=quality,
            scoped_quality=scoped_quality,
        )

    if coverage_ratio is None:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_DATA_COVERAGE_UNKNOWN",
            reason="Scanner candidate coverage ratio cannot be verified.",
            schema_version=schema_version,
            status=scoped_status,
            coverage_ratio=None,
            coverage_scope=coverage_scope,
            threshold=threshold,
            quality=quality,
            scoped_quality=scoped_quality,
        )

    if coverage_ratio < threshold:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_DATA_COVERAGE_BELOW_THRESHOLD",
            reason=(
                f"Scanner candidate {coverage_scope} coverage {coverage_ratio:.4f} is below "
                f"the required {threshold:.4f}."
            ),
            schema_version=schema_version,
            status=scoped_status,
            coverage_ratio=coverage_ratio,
            coverage_scope=coverage_scope,
            threshold=threshold,
            quality=quality,
            scoped_quality=scoped_quality,
        )

    return {
        "symbol": symbol,
        "decision": "PASS",
        "allowed": True,
        "reason_code": "SCANNER_DATA_QUALITY_ACCEPTED",
        "reason": "Scanner evidence satisfies the Manager data-quality gate.",
        "policy_version": SCANNER_DATA_QUALITY_POLICY_VERSION,
        "required_schema": SCANNER_DATA_BUNDLE_SCHEMA,
        "schema_version": schema_version,
        "status": scoped_status,
        "coverage_ratio": coverage_ratio,
        "coverage_scope": coverage_scope,
        "legacy_full_coverage_ratio": _finite_ratio(quality.get("coverage_ratio")),
        "min_coverage_ratio": threshold,
        "required_components": list(scoped_quality.get("required_components") or []),
        "missing_components": list(scoped_quality.get("missing_components") or []),
        "partial_components": list(scoped_quality.get("partial_components") or []),
        "market_missing_fields": list(quality.get("market_missing_fields") or []),
        "market_provider_errors": list(quality.get("market_provider_errors") or []),
    }


def partition_scanner_candidates_by_data_quality(
    candidates: Iterable[Any],
    *,
    min_coverage_ratio: Optional[float] = None,
) -> Tuple[List[Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Return candidates safe for downstream analysis plus REVIEW diagnostics."""

    passed: List[Any] = []
    review: List[Dict[str, Any]] = []
    evaluations: List[Dict[str, Any]] = []
    coverage_scope_counts: Dict[str, int] = {}
    for candidate in candidates or []:
        evaluation = evaluate_scanner_candidate_data_quality(
            candidate,
            min_coverage_ratio=min_coverage_ratio,
        )
        evaluations.append(evaluation)
        scope = str(evaluation.get("coverage_scope") or "unknown")
        coverage_scope_counts[scope] = coverage_scope_counts.get(scope, 0) + 1
        if evaluation["allowed"]:
            passed.append(candidate)
        else:
            review.append(evaluation)

    threshold = (
        scanner_min_data_coverage()
        if min_coverage_ratio is None
        else max(0.0, min(1.0, float(min_coverage_ratio)))
    )
    summary = {
        "policy_version": SCANNER_DATA_QUALITY_POLICY_VERSION,
        "required_schema": SCANNER_DATA_BUNDLE_SCHEMA,
        "min_coverage_ratio": threshold,
        "threshold_relaxed": False,
        "original_count": len(evaluations),
        "passed_count": len(passed),
        "review_count": len(review),
        "decision": "REVIEW" if review and not passed else "PARTIAL" if review else "PASS",
        "review_reason_codes": sorted({row["reason_code"] for row in review}),
        "coverage_scope_counts": dict(sorted(coverage_scope_counts.items())),
        "evaluations": evaluations,
    }
    return passed, review, summary
