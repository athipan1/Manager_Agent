from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping

from ..strategy_bucket_classifier import AUTO_CLASSIFY_THRESHOLD, KNOWN_BUCKETS
from .research_strategy_compatibility_service import (
    preflight_runtime_research_strategy_compatibility,
)

RESEARCH_BACKTEST_POLICY_VERSION = "manager-research-backtest-v4"
RESEARCH_RERANKER_VERSION = "manager-research-reranker-v3"
RESEARCH_ALLOWED_VERDICTS = {"hold", "buy", "strong_buy"}
EXPLORATORY_BUCKET = "exploratory"
RESEARCH_BUCKETS = frozenset({*KNOWN_BUCKETS, EXPLORATORY_BUCKET})
DEFAULT_RESEARCH_BUCKET_LIMITS = {
    "core_dividend": 3,
    "value_rebound": 3,
    "news_momentum": 2,
    EXPLORATORY_BUCKET: 2,
}
BUCKET_PRIORITY = (
    "core_dividend",
    "value_rebound",
    "news_momentum",
    EXPLORATORY_BUCKET,
)
DEFAULT_EXPLORATORY_MIN_CONFIDENCE = 0.60


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except Exception:
        return Decimal("0")


def _float(value: Any) -> float:
    try:
        return float(value if value not in (None, "") else 0.0)
    except (TypeError, ValueError):
        return 0.0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _final_score(row: Mapping[str, Any]) -> Decimal:
    score_breakdown = row.get("score_breakdown")
    if isinstance(score_breakdown, Mapping):
        return _decimal(score_breakdown.get("final_opportunity_score"))
    return _decimal(row.get("final_opportunity_score"))


def _verdict(row: Mapping[str, Any]) -> str:
    direct = row.get("final_verdict")
    if direct not in (None, ""):
        return str(direct).strip().lower()
    analysis = row.get("analysis")
    if isinstance(analysis, Mapping):
        return str(analysis.get("final_verdict") or "hold").strip().lower()
    return "hold"


def _scanner_opportunity_fail_closed(row: Mapping[str, Any]) -> bool:
    candidate = row.get("scanner_candidate")
    if not isinstance(candidate, Mapping):
        return False

    metadata = candidate.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    details = metadata.get("details")
    if not isinstance(details, Mapping):
        details = {}
    bundle = details.get("data_bundle")
    if not isinstance(bundle, Mapping):
        bundle = metadata.get("data_bundle")
    if not isinstance(bundle, Mapping):
        bundle = {}
    profile = bundle.get("opportunity_profile")
    if not isinstance(profile, Mapping):
        profile = {}
    return bool(profile.get("fail_closed"))


def _candidate_scorecard(row: Mapping[str, Any]) -> Mapping[str, Any]:
    direct = row.get("candidate_score_v1")
    if isinstance(direct, Mapping):
        return direct
    score_breakdown = _mapping(row.get("score_breakdown"))
    nested = score_breakdown.get("candidate_score_v1")
    return nested if isinstance(nested, Mapping) else {}


def _candidate_score_points(row: Mapping[str, Any]) -> float | None:
    scorecard = _candidate_scorecard(row)
    if not scorecard:
        return None
    raw = scorecard.get("score")
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(value, 10.0))


def _hard_gate_summary(row: Mapping[str, Any]) -> tuple[int, int]:
    gates = _mapping(_candidate_scorecard(row).get("hard_gates"))
    if not gates:
        return 0, 0
    total = len(gates)
    passed = sum(value is True for value in gates.values())
    return passed, total


def _reward_risk(row: Mapping[str, Any]) -> float | None:
    scorecard = _candidate_scorecard(row)
    criteria = _mapping(scorecard.get("criteria"))
    opportunity = _mapping(criteria.get("opportunity"))
    raw = opportunity.get("reward_risk")
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _evidence_coverage(row: Mapping[str, Any]) -> float | None:
    coverage = _mapping(_candidate_scorecard(row).get("evidence_coverage"))
    values: list[float] = []
    for key in ("fundamental", "technical", "scanner_analysis"):
        raw = coverage.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        values.append(max(0.0, min(value, 1.0)))
    if not values:
        return None
    return sum(values) / len(values)


def _bucket_confidence(row: Mapping[str, Any]) -> float:
    return max(0.0, min(_float(row.get("bucket_confidence")), 1.0))


def _exploratory_min_confidence() -> float:
    raw = str(
        os.getenv(
            "BACKTEST_RESEARCH_EXPLORATORY_MIN_CONFIDENCE",
            str(DEFAULT_EXPLORATORY_MIN_CONFIDENCE),
        )
    ).strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_EXPLORATORY_MIN_CONFIDENCE
    return max(0.0, min(value, AUTO_CLASSIFY_THRESHOLD))


def _research_rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Prefer evidence likely to survive later gates without making it binding."""

    score = _candidate_score_points(row)
    hard_passed, hard_total = _hard_gate_summary(row)
    hard_ratio = hard_passed / hard_total if hard_total else 0.0
    reward_risk = _reward_risk(row)
    coverage = _evidence_coverage(row)
    final_score = float(_final_score(row))

    if score is None:
        return (
            0,
            final_score,
            _bucket_confidence(row),
            0.0,
            0.0,
            0.0,
        )
    return (
        1,
        score,
        hard_ratio,
        reward_risk if reward_risk is not None else -1.0,
        coverage if coverage is not None else -1.0,
        final_score,
        _bucket_confidence(row),
    )


def _reranker_evidence(row: Mapping[str, Any]) -> Dict[str, Any]:
    score = _candidate_score_points(row)
    hard_passed, hard_total = _hard_gate_summary(row)
    return {
        "reranker_version": RESEARCH_RERANKER_VERSION,
        "candidate_score_available": score is not None,
        "candidate_score": score,
        "candidate_score_max": 10,
        "candidate_hard_gates_passed": hard_passed,
        "candidate_hard_gates_total": hard_total,
        "reward_risk": _reward_risk(row),
        "evidence_coverage": _evidence_coverage(row),
        "final_opportunity_score": float(_final_score(row)),
        "bucket_confidence": _bucket_confidence(row),
        "ordering_only": True,
        "production_binding": False,
        "thresholds_relaxed": False,
    }


def _normalize_research_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Route a near-classified row to broker-isolated strategy discovery.

    AUTO_CLASSIFY_THRESHOLD remains unchanged. A lower confidence may only enter
    the explicit exploratory research bucket, where production/Risk/Execution
    authority is false and exact Backtest remains mandatory.
    """

    normalized = dict(row)
    bucket = str(row.get("strategy_bucket") or row.get("bucket") or "").strip()
    status = str(row.get("bucket_classification_status") or "").strip()
    confidence = _bucket_confidence(row)
    production_classified = (
        bucket in KNOWN_BUCKETS
        and status == "classified"
        and confidence >= AUTO_CLASSIFY_THRESHOLD
    )
    if production_classified:
        normalized["research_strategy_discovery"] = False
        return normalized

    if confidence >= _exploratory_min_confidence():
        normalized["original_strategy_bucket"] = bucket or None
        normalized["original_bucket_classification_status"] = status or None
        normalized["strategy_bucket"] = EXPLORATORY_BUCKET
        # Backtest validates this explicit research bucket as a real bucket. It is
        # not a claim that the original production classifier passed.
        normalized["bucket_classification_status"] = "classified"
        normalized["research_strategy_discovery"] = True
        normalized["research_only_unclassified_source"] = True
        normalized["production_entry_authorized"] = False
        normalized["risk_execution_authorized"] = False
    return normalized


def _research_eligible(
    row: Mapping[str, Any],
    *,
    threshold: Decimal,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    bucket = str(row.get("strategy_bucket") or row.get("bucket") or "")
    exploratory = bucket == EXPLORATORY_BUCKET
    if bucket not in RESEARCH_BUCKETS:
        reasons.append("bucket_not_classified")
    if str(row.get("bucket_classification_status") or "") != "classified":
        reasons.append("classification_status_not_classified")
    confidence = _bucket_confidence(row)
    minimum_confidence = (
        _exploratory_min_confidence() if exploratory else AUTO_CLASSIFY_THRESHOLD
    )
    if confidence < minimum_confidence:
        reasons.append("bucket_confidence_below_threshold")
    if not bool(row.get("evidence_gate_passed", True)):
        reasons.append("evidence_gate_failed")
    if _final_score(row) < threshold:
        reasons.append("final_opportunity_score_below_threshold")
    verdict = _verdict(row)
    if verdict not in RESEARCH_ALLOWED_VERDICTS:
        reasons.append(f"verdict_not_research_eligible:{verdict}")
    if _scanner_opportunity_fail_closed(row):
        reasons.append("scanner_opportunity_fail_closed")
    return not reasons, reasons


def _compatibility_by_symbol(gate: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("symbol") or "").strip().upper(): item
        for item in gate.get("evaluations") or []
        if isinstance(item, Mapping) and str(item.get("symbol") or "").strip()
    }


def select_research_backtest_candidates(
    ranked_rows: Iterable[Mapping[str, Any]],
    *,
    min_final_score: float,
    bucket_limits: Mapping[str, int] | None = None,
) -> Dict[str, Any]:
    """Select broker-isolated research candidates for exact Backtest.

    Production classification and Backtest promotion thresholds stay intact.
    Near-classified rows may additionally enter the explicit exploratory bucket,
    which can spend research Backtest capacity but can never authorize Risk,
    Execution, or broker mutation by itself.
    """

    threshold = Decimal(str(min_final_score))
    limits = {**DEFAULT_RESEARCH_BUCKET_LIMITS, **dict(bucket_limits or {})}
    original_rows = [dict(row) for row in ranked_rows if isinstance(row, Mapping)]
    normalized_rows = [_normalize_research_row(row) for row in original_rows]
    rows, compatibility_gate = preflight_runtime_research_strategy_compatibility(
        normalized_rows
    )
    compatibility = _compatibility_by_symbol(compatibility_gate)
    rejected_for_compatibility = set(
        str(symbol or "").strip().upper()
        for symbol in compatibility_gate.get("rejected_symbols") or []
        if str(symbol or "").strip()
    )

    selected: list[Dict[str, Any]] = []
    evaluations: list[Dict[str, Any]] = []

    for row in normalized_rows:
        eligible, reasons = _research_eligible(row, threshold=threshold)
        symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if symbol in rejected_for_compatibility:
            eligible = False
            reasons = [*reasons, "insufficient_strategy_diversity"]
        evaluations.append(
            {
                "symbol": row.get("symbol") or row.get("ticker"),
                "strategy_bucket": row.get("strategy_bucket") or row.get("bucket"),
                "original_strategy_bucket": row.get("original_strategy_bucket"),
                "research_strategy_discovery": bool(
                    row.get("research_strategy_discovery")
                ),
                "final_verdict": _verdict(row),
                "final_opportunity_score": float(_final_score(row)),
                "eligible": eligible,
                "reasons": reasons,
                "reranker": _reranker_evidence(row),
                "strategy_compatibility": compatibility.get(symbol),
            }
        )

    for bucket in BUCKET_PRIORITY:
        eligible_rows = [
            row
            for row in rows
            if str(row.get("strategy_bucket") or row.get("bucket") or "") == bucket
            and _research_eligible(row, threshold=threshold)[0]
        ]
        eligible_rows.sort(key=_research_rank_key, reverse=True)
        limit = max(0, int(limits.get(bucket, 0)))
        for row in eligible_rows[:limit]:
            symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
            if not symbol or any(item["symbol"] == symbol for item in selected):
                continue
            exploratory = bucket == EXPLORATORY_BUCKET
            selected.append(
                {
                    "symbol": symbol,
                    "strategy_bucket": bucket,
                    "original_strategy_bucket": row.get("original_strategy_bucket"),
                    "bucket_confidence": row.get("bucket_confidence"),
                    "bucket_classification_status": row.get("bucket_classification_status"),
                    "original_bucket_classification_status": row.get(
                        "original_bucket_classification_status"
                    ),
                    "evidence_gate_passed": bool(row.get("evidence_gate_passed", True)),
                    "final_verdict": _verdict(row),
                    "final_opportunity_score": float(_final_score(row)),
                    "research_reranker": _reranker_evidence(row),
                    "pre_backtest_strategy_compatibility": row.get(
                        "pre_backtest_strategy_compatibility"
                    ),
                    "selection_lane": (
                        "research_strategy_discovery"
                        if exploratory
                        else "research_backtest"
                    ),
                    "research_strategy_discovery": exploratory,
                    "production_entry_authorized": False,
                    "risk_execution_authorized": False,
                }
            )

    return {
        "policy_version": RESEARCH_BACKTEST_POLICY_VERSION,
        "reranker_version": RESEARCH_RERANKER_VERSION,
        "min_final_score": float(threshold),
        "allowed_verdicts": sorted(RESEARCH_ALLOWED_VERDICTS),
        "auto_classify_threshold": AUTO_CLASSIFY_THRESHOLD,
        "exploratory_min_confidence": _exploratory_min_confidence(),
        "selected_count": len(selected),
        "selected": selected,
        "evaluations": evaluations,
        "strategy_compatibility_gate": compatibility_gate,
        "reranker_policy": {
            "candidate_score_is_ordering_only": True,
            "legacy_fallback": "final_opportunity_score",
            "production_binding": False,
            "thresholds_relaxed": False,
        },
        "exploratory_policy": {
            "bucket": EXPLORATORY_BUCKET,
            "research_only": True,
            "production_auto_classify_threshold_unchanged": True,
            "exact_backtest_required": True,
            "production_binding": False,
            "risk_execution_authority_granted": False,
            "broker_order_authorized": False,
        },
        "production_entry_authorized": False,
        "risk_execution_authorized": False,
    }
