from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Mapping, Optional

from .strategy_bucket_classifier import (
    AUTO_CLASSIFY_THRESHOLD,
    CLASSIFIER_VERSION,
    CORE_DIVIDEND,
    KNOWN_BUCKETS,
    NEWS_MOMENTUM,
    StrategyBucketClassification,
    UNASSIGNED,
    VALUE_REBOUND,
    classify_candidate_strategy_bucket,
)


@dataclass(frozen=True)
class StrategyBucketPolicy:
    name: str
    target_weight: Decimal
    max_symbol_weight: Decimal
    min_final_score: Decimal
    max_positions: int
    description: str


DEFAULT_BUCKET_POLICIES: Dict[str, StrategyBucketPolicy] = {
    CORE_DIVIDEND: StrategyBucketPolicy(
        name=CORE_DIVIDEND,
        target_weight=Decimal("0.50"),
        max_symbol_weight=Decimal("0.10"),
        min_final_score=Decimal("0.55"),
        max_positions=8,
        description=(
            "หุ้นพื้นฐานดี ปลอดภัย มีปันผล หรือคุณภาพสูง "
            "ถือเป็นแกนหลักของพอร์ต"
        ),
    ),
    VALUE_REBOUND: StrategyBucketPolicy(
        name=VALUE_REBOUND,
        target_weight=Decimal("0.30"),
        max_symbol_weight=Decimal("0.07"),
        min_final_score=Decimal("0.58"),
        max_positions=6,
        description=(
            "หุ้นราคาถูกหรือ valuation น่าสนใจ เพื่อรอขายทำกำไร"
        ),
    ),
    NEWS_MOMENTUM: StrategyBucketPolicy(
        name=NEWS_MOMENTUM,
        target_weight=Decimal("0.20"),
        max_symbol_weight=Decimal("0.03"),
        min_final_score=Decimal("0.62"),
        max_positions=5,
        description=(
            "หุ้นเทรดตามข่าว momentum หรือ catalyst ระยะสั้น "
            "จำกัดน้ำหนักต่อไม้ต่ำสุด"
        ),
    ),
}


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except Exception:
        return default


def classify_strategy_bucket_decision(
    item: Mapping[str, Any],
) -> StrategyBucketClassification:
    """Return Manager's governed classification and evidence decision."""
    return classify_candidate_strategy_bucket(item)


def classify_strategy_bucket(item: Mapping[str, Any]) -> str:
    """Backward-compatible bucket-only view of the governed classifier."""
    return classify_strategy_bucket_decision(item).bucket


def _classification_payload(item: Mapping[str, Any]) -> Dict[str, Any]:
    existing = item.get("strategy_bucket_classification")
    if isinstance(existing, Mapping):
        return dict(existing)
    return classify_strategy_bucket_decision(item).as_dict()


def build_strategy_allocation_plan(
    ranked_candidates: List[Mapping[str, Any]],
    portfolio_value: Decimal,
    policies: Optional[Dict[str, StrategyBucketPolicy]] = None,
) -> Dict[str, Any]:
    policies = policies or DEFAULT_BUCKET_POLICIES
    portfolio_value = _decimal(portfolio_value)

    buckets: Dict[str, Dict[str, Any]] = {}
    for name, policy in policies.items():
        target_value = (
            portfolio_value * policy.target_weight
        ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        buckets[name] = {
            "target_weight": float(policy.target_weight),
            "target_value": float(target_value),
            "max_symbol_weight": float(policy.max_symbol_weight),
            "max_symbol_value": float(
                (
                    portfolio_value * policy.max_symbol_weight
                ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            ),
            "min_final_score": float(policy.min_final_score),
            "max_positions": policy.max_positions,
            "description": policy.description,
            "candidates": [],
        }
    quarantine: List[Dict[str, Any]] = []

    for item in ranked_candidates:
        classification = _classification_payload(item)
        bucket_name = str(
            classification.get("bucket") or UNASSIGNED
        )
        confidence = float(classification.get("confidence") or 0.0)
        status = str(
            classification.get("status") or "unassigned"
        )
        evidence_gate_passed = bool(
            classification.get("evidence_gate_passed", True)
        )
        evidence_summary = dict(
            classification.get("evidence_summary") or {}
        )

        if (
            bucket_name not in buckets
            or bucket_name not in KNOWN_BUCKETS
            or status != "classified"
            or confidence < AUTO_CLASSIFY_THRESHOLD
            or not evidence_gate_passed
        ):
            quarantine.append(
                {
                    "symbol": item.get("symbol"),
                    "strategy_bucket": UNASSIGNED,
                    "proposed_bucket": classification.get(
                        "proposed_bucket"
                    ),
                    "bucket_confidence": confidence,
                    "classification_status": status,
                    "classification_reasons": list(
                        classification.get("reasons") or []
                    ),
                    "classifier_version": (
                        classification.get("classifier_version")
                        or CLASSIFIER_VERSION
                    ),
                    "evidence_gate_passed": evidence_gate_passed,
                    "evidence_versions": evidence_summary.get(
                        "evidence_versions"
                    )
                    or {},
                    "evidence_statuses": evidence_summary.get(
                        "evidence_statuses"
                    )
                    or {},
                    "evidence_blocking_issues": evidence_summary.get(
                        "blocking_issues"
                    )
                    or [],
                    "source_conflicts": evidence_summary.get(
                        "source_conflicts"
                    )
                    or [],
                    "blocked_reason": (
                        "analysis_evidence_gate_failed"
                        if not evidence_gate_passed
                        else "strategy_bucket_not_auto_approved"
                    ),
                }
            )
            continue

        policy = policies[bucket_name]
        score = _decimal(
            (item.get("score_breakdown") or {}).get(
                "final_opportunity_score"
            )
        )
        if score < policy.min_final_score:
            continue
        if (
            len(buckets[bucket_name]["candidates"])
            >= policy.max_positions
        ):
            continue
        candidate_count = max(
            1,
            min(
                policy.max_positions,
                len(buckets[bucket_name]["candidates"]) + 1,
            ),
        )
        buckets[bucket_name]["candidates"].append(
            {
                "symbol": item.get("symbol"),
                "bucket": bucket_name,
                "strategy_bucket": bucket_name,
                "bucket_confidence": confidence,
                "classification_status": status,
                "classification_reasons": list(
                    classification.get("reasons") or []
                ),
                "classifier_version": (
                    classification.get("classifier_version")
                    or CLASSIFIER_VERSION
                ),
                "evidence_gate_passed": evidence_gate_passed,
                "evidence_versions": evidence_summary.get(
                    "evidence_versions"
                )
                or {},
                "evidence_statuses": evidence_summary.get(
                    "evidence_statuses"
                )
                or {},
                "final_opportunity_score": float(score),
                "suggested_max_value": buckets[bucket_name][
                    "max_symbol_value"
                ],
                "suggested_equal_weight_value": float(
                    (
                        Decimal(
                            str(buckets[bucket_name]["target_value"])
                        )
                        / Decimal(candidate_count)
                    ).quantize(
                        Decimal("0.01"),
                        rounding=ROUND_DOWN,
                    )
                ),
            }
        )

    total_target_weight = sum(
        policy.target_weight for policy in policies.values()
    )
    return {
        "policy_name": "core_satellite_50_30_20",
        "portfolio_value": float(portfolio_value),
        "total_target_weight": float(total_target_weight),
        "is_weight_balanced": (
            total_target_weight == Decimal("1.00")
        ),
        "classifier_version": CLASSIFIER_VERSION,
        "evidence_contract": "manager-analysis-evidence-v1",
        "auto_classify_threshold": AUTO_CLASSIFY_THRESHOLD,
        "buckets": buckets,
        "quarantine": quarantine,
        "quarantine_count": len(quarantine),
    }
