from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping

from ..strategy_bucket_classifier import AUTO_CLASSIFY_THRESHOLD, KNOWN_BUCKETS

RESEARCH_BACKTEST_POLICY_VERSION = "manager-research-backtest-v1"
RESEARCH_ALLOWED_VERDICTS = {"hold", "buy", "strong_buy"}
DEFAULT_RESEARCH_BUCKET_LIMITS = {
    "core_dividend": 2,
    "value_rebound": 2,
    "news_momentum": 1,
}
BUCKET_PRIORITY = ("core_dividend", "value_rebound", "news_momentum")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except Exception:
        return Decimal("0")


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


def _research_eligible(
    row: Mapping[str, Any],
    *,
    threshold: Decimal,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    bucket = str(row.get("strategy_bucket") or row.get("bucket") or "")
    if bucket not in KNOWN_BUCKETS:
        reasons.append("bucket_not_classified")
    if str(row.get("bucket_classification_status") or "") != "classified":
        reasons.append("classification_status_not_classified")
    try:
        confidence = float(row.get("bucket_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < AUTO_CLASSIFY_THRESHOLD:
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


def select_research_backtest_candidates(
    ranked_rows: Iterable[Mapping[str, Any]],
    *,
    min_final_score: float,
    bucket_limits: Mapping[str, int] | None = None,
) -> Dict[str, Any]:
    """Select broker-isolated research candidates for exact Backtest.

    This selector intentionally differs from the production entry selector:
    a HOLD verdict may proceed to historical Backtest when classification,
    evidence and score gates pass. SELL/STRONG_SELL and explicit fail-closed
    Scanner evidence remain blocked. The result has no Risk/Execution authority.
    """

    threshold = Decimal(str(min_final_score))
    limits = {**DEFAULT_RESEARCH_BUCKET_LIMITS, **dict(bucket_limits or {})}
    rows = [dict(row) for row in ranked_rows if isinstance(row, Mapping)]
    selected: list[Dict[str, Any]] = []
    evaluations: list[Dict[str, Any]] = []

    for row in rows:
        eligible, reasons = _research_eligible(row, threshold=threshold)
        evaluations.append(
            {
                "symbol": row.get("symbol") or row.get("ticker"),
                "strategy_bucket": row.get("strategy_bucket") or row.get("bucket"),
                "final_verdict": _verdict(row),
                "final_opportunity_score": float(_final_score(row)),
                "eligible": eligible,
                "reasons": reasons,
            }
        )

    for bucket in BUCKET_PRIORITY:
        eligible_rows = [
            row
            for row in rows
            if str(row.get("strategy_bucket") or row.get("bucket") or "") == bucket
            and _research_eligible(row, threshold=threshold)[0]
        ]
        eligible_rows.sort(key=_final_score, reverse=True)
        limit = max(0, int(limits.get(bucket, 0)))
        for row in eligible_rows[:limit]:
            symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
            if not symbol or any(item["symbol"] == symbol for item in selected):
                continue
            selected.append(
                {
                    "symbol": symbol,
                    "strategy_bucket": bucket,
                    "bucket_confidence": row.get("bucket_confidence"),
                    "bucket_classification_status": row.get("bucket_classification_status"),
                    "evidence_gate_passed": bool(row.get("evidence_gate_passed", True)),
                    "final_verdict": _verdict(row),
                    "final_opportunity_score": float(_final_score(row)),
                    "selection_lane": "research_backtest",
                    "production_entry_authorized": False,
                    "risk_execution_authorized": False,
                }
            )

    return {
        "policy_version": RESEARCH_BACKTEST_POLICY_VERSION,
        "min_final_score": float(threshold),
        "allowed_verdicts": sorted(RESEARCH_ALLOWED_VERDICTS),
        "auto_classify_threshold": AUTO_CLASSIFY_THRESHOLD,
        "selected_count": len(selected),
        "selected": selected,
        "evaluations": evaluations,
        "production_entry_authorized": False,
        "risk_execution_authorized": False,
    }
