from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Iterable, List, Mapping, Optional


CORE_DIVIDEND = "core_dividend"
VALUE_REBOUND = "value_rebound"
NEWS_MOMENTUM = "news_momentum"
UNASSIGNED = "unassigned"


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
        description="หุ้นพื้นฐานดี ปลอดภัย มีปันผล หรือคุณภาพสูง ถือเป็นแกนหลักของพอร์ต",
    ),
    VALUE_REBOUND: StrategyBucketPolicy(
        name=VALUE_REBOUND,
        target_weight=Decimal("0.30"),
        max_symbol_weight=Decimal("0.07"),
        min_final_score=Decimal("0.58"),
        max_positions=6,
        description="หุ้นราคาถูกหรือ valuation น่าสนใจ เพื่อรอขายทำกำไร",
    ),
    NEWS_MOMENTUM: StrategyBucketPolicy(
        name=NEWS_MOMENTUM,
        target_weight=Decimal("0.20"),
        max_symbol_weight=Decimal("0.03"),
        min_final_score=Decimal("0.62"),
        max_positions=5,
        description="หุ้นเทรดตามข่าว momentum หรือ catalyst ระยะสั้น จำกัดน้ำหนักต่อไม้ต่ำสุด",
    ),
}


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _nested_get(mapping: Mapping[str, Any], path: Iterable[str], default: Any = None) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return default if current is None else current


def _analysis_details(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    details = analysis.get("details") or {}
    return details if isinstance(details, Mapping) else {}


def _fundamental_scores(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    details = _analysis_details(analysis)
    fundamental = details.get("fundamental_analysis") or details.get("fundamental") or {}
    if hasattr(fundamental, "model_dump"):
        fundamental = fundamental.model_dump(mode="json")
    if not isinstance(fundamental, Mapping):
        return {}
    return fundamental


def _scanner_metadata(item: Mapping[str, Any]) -> Mapping[str, Any]:
    scanner = item.get("scanner_candidate") or {}
    if hasattr(scanner, "model_dump"):
        scanner = scanner.model_dump(mode="json")
    if isinstance(scanner, Mapping):
        metadata = scanner.get("metadata") or {}
        return metadata if isinstance(metadata, Mapping) else {}
    return {}


def _raw_scores(item: Mapping[str, Any]) -> Mapping[str, Any]:
    scanner = item.get("scanner_candidate") or {}
    if hasattr(scanner, "model_dump"):
        scanner = scanner.model_dump(mode="json")
    if isinstance(scanner, Mapping):
        raw_scores = scanner.get("raw_scores") or {}
        return raw_scores if isinstance(raw_scores, Mapping) else {}
    return {}


def classify_strategy_bucket(item: Mapping[str, Any]) -> str:
    """
    Classify a ranked candidate into one of the user's 3 allocation buckets.

    This is intentionally deterministic and conservative. Later agents can provide
    richer explicit labels, but Manager can already bucket candidates from the
    current scanner/fundamental payload.
    """
    analysis = item.get("analysis") or {}
    if hasattr(analysis, "model_dump"):
        analysis = analysis.model_dump(mode="json")
    analysis = analysis if isinstance(analysis, Mapping) else {}

    score_breakdown = item.get("score_breakdown") or {}
    score = _decimal(score_breakdown.get("final_opportunity_score"))
    metadata = _scanner_metadata(item)
    raw_scores = _raw_scores(item)
    fundamental = _fundamental_scores(analysis)

    tags = item.get("tags") or metadata.get("tags") or []
    tag_text = " ".join(str(tag).lower() for tag in tags) if isinstance(tags, list) else str(tags).lower()
    sector = str(metadata.get("sector") or fundamental.get("sector") or "").lower()

    dividend_yield = _decimal(
        raw_scores.get("dividend_yield")
        or fundamental.get("dividend_yield")
        or _nested_get(fundamental, ["metrics", "dividend_yield"])
    )
    quality_score = _decimal(raw_scores.get("quality_score") or fundamental.get("quality_score"))
    pe_ratio = _decimal(raw_scores.get("pe_ratio") or fundamental.get("pe_ratio"), Decimal("999"))
    pb_ratio = _decimal(raw_scores.get("pb_ratio") or fundamental.get("pb_ratio"), Decimal("999"))
    growth_score = _decimal(raw_scores.get("growth_score") or fundamental.get("growth_score"))

    news_hints = ("news", "catalyst", "momentum", "volume", "breakout", "trend")
    value_hints = ("value", "cheap", "undervalued", "rebound", "discount", "valuation")
    core_hints = ("dividend", "quality", "defensive", "blue-chip", "stable", "cash-flow")

    if any(hint in tag_text for hint in news_hints):
        return NEWS_MOMENTUM
    if any(hint in tag_text for hint in value_hints):
        return VALUE_REBOUND
    if any(hint in tag_text for hint in core_hints):
        return CORE_DIVIDEND

    if dividend_yield > Decimal("0") or sector in {"utilities", "consumer defensive", "healthcare", "financial services"}:
        return CORE_DIVIDEND
    if quality_score >= Decimal("70") and score >= Decimal("0.55"):
        return CORE_DIVIDEND
    if pe_ratio > Decimal("0") and pe_ratio <= Decimal("15"):
        return VALUE_REBOUND
    if pb_ratio > Decimal("0") and pb_ratio <= Decimal("1.5"):
        return VALUE_REBOUND
    if growth_score >= Decimal("70") and score >= Decimal("0.62"):
        return NEWS_MOMENTUM

    return VALUE_REBOUND


def build_strategy_allocation_plan(
    ranked_candidates: List[Mapping[str, Any]],
    portfolio_value: Decimal,
    policies: Optional[Dict[str, StrategyBucketPolicy]] = None,
) -> Dict[str, Any]:
    policies = policies or DEFAULT_BUCKET_POLICIES
    portfolio_value = _decimal(portfolio_value)

    buckets: Dict[str, Dict[str, Any]] = {}
    for name, policy in policies.items():
        target_value = (portfolio_value * policy.target_weight).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        buckets[name] = {
            "target_weight": float(policy.target_weight),
            "target_value": float(target_value),
            "max_symbol_weight": float(policy.max_symbol_weight),
            "max_symbol_value": float((portfolio_value * policy.max_symbol_weight).quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
            "min_final_score": float(policy.min_final_score),
            "max_positions": policy.max_positions,
            "description": policy.description,
            "candidates": [],
        }

    for item in ranked_candidates:
        bucket_name = classify_strategy_bucket(item)
        if bucket_name not in buckets:
            bucket_name = VALUE_REBOUND
        policy = policies[bucket_name]
        score = _decimal((item.get("score_breakdown") or {}).get("final_opportunity_score"))
        if score < policy.min_final_score:
            continue
        if len(buckets[bucket_name]["candidates"]) >= policy.max_positions:
            continue
        candidate_count = max(1, min(policy.max_positions, len(buckets[bucket_name]["candidates"]) + 1))
        buckets[bucket_name]["candidates"].append(
            {
                "symbol": item.get("symbol"),
                "bucket": bucket_name,
                "final_opportunity_score": float(score),
                "suggested_max_value": buckets[bucket_name]["max_symbol_value"],
                "suggested_equal_weight_value": float(
                    (Decimal(str(buckets[bucket_name]["target_value"])) / Decimal(candidate_count)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                ),
            }
        )

    total_target_weight = sum(policy.target_weight for policy in policies.values())
    return {
        "policy_name": "core_satellite_50_30_20",
        "portfolio_value": float(portfolio_value),
        "total_target_weight": float(total_target_weight),
        "is_weight_balanced": total_target_weight == Decimal("1.00"),
        "buckets": buckets,
    }
