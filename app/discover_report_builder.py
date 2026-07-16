from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping

from . import config
from .discover_allocation import (
    build_discover_allocation_plan,
    choose_bucket_aware_winner,
    enrich_ranked_candidates_with_buckets,
    ranked_response_rows,
    select_candidates_by_bucket,
)
from .portfolio_allocation import UNASSIGNED
from .services.investability_gate import filter_candidates_with_investability_gate
from .services.pre_risk_capacity_service import (
    DEFAULT_MIN_INCREMENTAL_VALUE,
    apply_pre_risk_capacity_selection,
)


def _selected_rows(bucket_selection: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for bucket_name, bucket_data in bucket_selection.items():
        if bucket_name == "summary" or not isinstance(bucket_data, dict):
            continue
        for row in bucket_data.get("selected") or []:
            if not isinstance(row, Mapping):
                continue
            next_row = dict(row)
            next_row.setdefault("strategy_bucket", bucket_name)
            rows.append(next_row)
    return rows


def _selected_symbols(bucket_selection: Dict[str, Any]) -> List[str]:
    symbols: List[str] = []
    for row in _selected_rows(bucket_selection):
        symbol = row.get("symbol")
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _bucket_candidate(
    allocation_plan: Dict[str, Any],
    symbol: str,
    bucket: str,
) -> Dict[str, Any]:
    bucket_data = (allocation_plan.get("buckets") or {}).get(bucket) or {}
    for candidate in bucket_data.get("candidates") or []:
        if str(candidate.get("symbol") or "").upper() == str(symbol or "").upper():
            return candidate
    return {}


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _per_symbol_target_value(
    *,
    selected_row: Mapping[str, Any],
    candidate_meta: Mapping[str, Any],
    bucket_plan: Mapping[str, Any],
) -> float | None:
    """Return final symbol target, never the whole bucket target."""

    explicit = _positive_float(
        selected_row.get("capacity_adjusted_target_value")
        or selected_row.get("target_value")
    )
    if explicit is not None:
        return explicit

    candidates = [
        value
        for value in (
            _positive_float(candidate_meta.get("suggested_equal_weight_value")),
            _positive_float(candidate_meta.get("suggested_max_value")),
            _positive_float(bucket_plan.get("max_symbol_value")),
        )
        if value is not None
    ]
    return min(candidates) if candidates else None


def build_selected_positions(
    *,
    ranked: List[Dict[str, Any]],
    allocation_plan: Dict[str, Any],
    bucket_selection: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build positions that passed classification, evidence and capacity gates."""

    ranked_by_symbol = {
        str(item.get("symbol") or "").upper(): item
        for item in ranked
    }
    selected_rows = {
        str(row.get("symbol") or "").upper(): row
        for row in _selected_rows(bucket_selection)
        if row.get("symbol")
    }
    selected_positions: List[Dict[str, Any]] = []

    for symbol in _selected_symbols(bucket_selection):
        item = ranked_by_symbol.get(str(symbol).upper())
        selected_row = selected_rows.get(str(symbol).upper(), {})
        if not item:
            continue
        bucket = item.get("strategy_bucket") or (
            item.get("score_breakdown") or {}
        ).get("strategy_bucket")
        if not bucket or bucket == UNASSIGNED:
            continue
        bucket_plan = (allocation_plan.get("buckets") or {}).get(bucket) or {}
        candidate_meta = _bucket_candidate(allocation_plan, symbol, bucket)
        target_weight = bucket_plan.get("target_weight") or 0
        evidence_summary = dict(item.get("evidence_summary") or {})
        target_value = _per_symbol_target_value(
            selected_row=selected_row,
            candidate_meta=candidate_meta,
            bucket_plan=bucket_plan,
        )
        selected_positions.append(
            {
                "symbol": symbol,
                "bucket": bucket,
                "strategy_bucket": bucket,
                "bucket_confidence": item.get("bucket_confidence"),
                "bucket_classification_status": item.get(
                    "bucket_classification_status"
                ),
                "bucket_classification_reasons": item.get(
                    "bucket_classification_reasons"
                )
                or [],
                "bucket_classifier_version": item.get(
                    "bucket_classifier_version"
                ),
                "strategy_bucket_classification": item.get(
                    "strategy_bucket_classification"
                )
                or {},
                "evidence_gate_passed": item.get("evidence_gate_passed", True),
                "evidence_summary": evidence_summary,
                "evidence_versions": evidence_summary.get("evidence_versions") or {},
                "evidence_statuses": evidence_summary.get("evidence_statuses") or {},
                "source_conflicts": evidence_summary.get("source_conflicts") or [],
                "target_weight": target_weight,
                "allocation_pct": float(target_weight) * 100,
                "bucket_target_value": bucket_plan.get("target_value"),
                "target_value": target_value,
                "suggested_max_value": candidate_meta.get("suggested_max_value")
                or bucket_plan.get("max_symbol_value"),
                "suggested_equal_weight_value": candidate_meta.get(
                    "suggested_equal_weight_value"
                ),
                "capacity_adjusted_target_value": selected_row.get(
                    "capacity_adjusted_target_value"
                ),
                "capacity_incremental_value": selected_row.get(
                    "capacity_incremental_value"
                ),
                "capacity_policy_version": selected_row.get(
                    "capacity_policy_version"
                ),
                "pre_risk_capacity": selected_row.get("pre_risk_capacity") or {},
                "capacity_fallback_promoted": bool(
                    selected_row.get("capacity_fallback_promoted")
                ),
                "final_verdict": (item.get("analysis") or {}).get("final_verdict"),
                "analysis_status": (item.get("analysis") or {}).get("status"),
                "score_breakdown": item.get("score_breakdown"),
                "scanner_candidate": item.get("scanner_candidate"),
            }
        )
    return selected_positions


def build_position_analysis_payloads(
    *,
    ranked: List[Dict[str, Any]],
    selected_positions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach allocation, classifier, evidence and capacity context for Risk."""

    ranked_by_symbol = {
        str(item.get("symbol") or "").upper(): item
        for item in ranked
    }
    payloads: List[Dict[str, Any]] = []

    for position in selected_positions:
        symbol = str(position.get("symbol") or "").upper()
        item = ranked_by_symbol.get(symbol)
        if not item:
            continue
        analysis = dict(item.get("analysis") or {})
        evidence_summary = dict(
            position.get("evidence_summary")
            or item.get("evidence_summary")
            or {}
        )
        analysis["scanner_candidate"] = item.get("scanner_candidate")
        analysis["score_breakdown"] = item.get("score_breakdown")
        analysis["strategy_bucket"] = (
            position.get("strategy_bucket") or position.get("bucket")
        )
        analysis["strategy_bucket_classification"] = (
            position.get("strategy_bucket_classification") or {}
        )
        analysis["bucket_confidence"] = position.get("bucket_confidence")
        analysis["bucket_classification_status"] = position.get(
            "bucket_classification_status"
        )
        analysis["bucket_classification_reasons"] = (
            position.get("bucket_classification_reasons") or []
        )
        analysis["bucket_classifier_version"] = position.get(
            "bucket_classifier_version"
        )
        analysis["evidence_gate_passed"] = position.get(
            "evidence_gate_passed",
            True,
        )
        analysis["evidence_summary"] = evidence_summary
        analysis["evidence_versions"] = evidence_summary.get("evidence_versions") or {}
        analysis["fundamental_evidence_status"] = (
            evidence_summary.get("evidence_statuses") or {}
        ).get("fundamental")
        analysis["technical_evidence_status"] = (
            evidence_summary.get("evidence_statuses") or {}
        ).get("technical")
        analysis["source_conflicts"] = evidence_summary.get("source_conflicts") or []
        analysis["classification_inputs"] = evidence_summary.get(
            "classification_inputs"
        ) or {}
        analysis["portfolio_context"] = {
            "bucket": position.get("bucket"),
            "strategy_bucket": position.get("strategy_bucket"),
            "bucket_confidence": position.get("bucket_confidence"),
            "bucket_classification_status": position.get(
                "bucket_classification_status"
            ),
            "bucket_classification_reasons": position.get(
                "bucket_classification_reasons"
            )
            or [],
            "bucket_classifier_version": position.get(
                "bucket_classifier_version"
            ),
            "evidence_gate_passed": position.get("evidence_gate_passed", True),
            "evidence_versions": evidence_summary.get("evidence_versions") or {},
            "evidence_statuses": evidence_summary.get("evidence_statuses") or {},
            "source_conflicts": evidence_summary.get("source_conflicts") or [],
            "target_weight": position.get("target_weight"),
            "allocation_pct": position.get("allocation_pct"),
            "bucket_target_value": position.get("bucket_target_value"),
            "target_value": position.get("target_value"),
            "suggested_max_value": position.get("suggested_max_value"),
            "suggested_equal_weight_value": position.get(
                "suggested_equal_weight_value"
            ),
            "capacity_adjusted_target_value": position.get(
                "capacity_adjusted_target_value"
            ),
            "capacity_incremental_value": position.get(
                "capacity_incremental_value"
            ),
            "capacity_policy_version": position.get("capacity_policy_version"),
            "capacity_fallback_promoted": position.get(
                "capacity_fallback_promoted"
            ),
            "pre_risk_capacity": position.get("pre_risk_capacity") or {},
        }
        payloads.append(analysis)
    return payloads


def _investability_filter(
    *,
    selected_positions: List[Dict[str, Any]],
    position_analysis_payloads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return filter_candidates_with_investability_gate(
        selected_positions=selected_positions,
        position_analysis_payloads=position_analysis_payloads,
        enabled=config.INVESTABILITY_GATE_ENABLED,
        min_price_usd=config.INVESTABILITY_MIN_PRICE_USD,
        min_market_cap_usd=config.INVESTABILITY_MIN_MARKET_CAP_USD,
        min_average_dollar_volume_usd=(
            config.INVESTABILITY_MIN_AVG_DOLLAR_VOLUME_USD
        ),
        max_spread_bps=config.INVESTABILITY_MAX_SPREAD_BPS,
        max_atr_pct=config.INVESTABILITY_MAX_ATR_PCT,
        require_average_dollar_volume=(
            config.INVESTABILITY_REQUIRE_AVG_DOLLAR_VOLUME
        ),
        require_spread=config.INVESTABILITY_REQUIRE_SPREAD,
        require_atr=config.INVESTABILITY_REQUIRE_ATR,
        block_extreme_volatility=(
            config.INVESTABILITY_BLOCK_EXTREME_VOLATILITY
        ),
    )


def _attach_investability_to_ranked_rows(
    rows: List[Dict[str, Any]],
    gate: Dict[str, Any],
) -> List[Dict[str, Any]]:
    decisions = {
        str(row.get("symbol") or "").upper(): row
        for row in gate.get("decisions") or []
        if row.get("symbol")
    }
    result: List[Dict[str, Any]] = []
    for row in rows:
        next_row = dict(row)
        decision = decisions.get(str(row.get("symbol") or "").upper())
        if decision is not None:
            next_row["investability_gate"] = decision
        result.append(next_row)
    return result


def build_discover_allocation_report(
    *,
    ranked: List[Dict[str, Any]],
    portfolio_value: Any,
    min_final_score: float,
    positions: Iterable[Any] | None = None,
    minimum_incremental_value: Any = DEFAULT_MIN_INCREMENTAL_VALUE,
) -> Dict[str, Any]:
    """Build governed allocation and filter non-investable names pre-Backtest."""

    enriched_ranked = enrich_ranked_candidates_with_buckets(ranked)
    allocation_plan = build_discover_allocation_plan(
        enriched_ranked,
        Decimal(str(portfolio_value or 0)),
    )
    bucket_selection = select_candidates_by_bucket(
        enriched_ranked,
        min_final_score=min_final_score,
    )
    capacity_selection = apply_pre_risk_capacity_selection(
        ranked=enriched_ranked,
        allocation_plan=allocation_plan,
        bucket_selection=bucket_selection,
        positions=list(positions or []),
        portfolio_value=portfolio_value,
        minimum_incremental_value=minimum_incremental_value,
    )
    bucket_selection = capacity_selection["bucket_selection"]
    selected_before_investability = build_selected_positions(
        ranked=enriched_ranked,
        allocation_plan=allocation_plan,
        bucket_selection=bucket_selection,
    )
    payloads_before_investability = build_position_analysis_payloads(
        ranked=enriched_ranked,
        selected_positions=selected_before_investability,
    )
    investability_gate = _investability_filter(
        selected_positions=selected_before_investability,
        position_analysis_payloads=payloads_before_investability,
    )
    selected_positions = investability_gate["selected_positions"]
    position_analysis_payloads = investability_gate[
        "position_analysis_payloads"
    ]

    allocation_plan = dict(allocation_plan)
    allocation_plan["investability_gate"] = investability_gate
    bucket_selection = dict(bucket_selection)
    bucket_summary = dict(bucket_selection.get("summary") or {})
    bucket_summary.update(
        {
            "selected_before_investability": len(
                selected_before_investability
            ),
            "selected_after_investability": len(selected_positions),
            "investability_gate_enabled": investability_gate.get("enabled"),
            "investability_gate_policy_version": investability_gate.get(
                "policy_version"
            ),
            "investability_rejected_count": (
                investability_gate.get("summary") or {}
            ).get("rejected_count", 0),
            "investability_rejected_symbols": [
                row.get("symbol")
                for row in investability_gate.get("rejected") or []
            ],
        }
    )
    bucket_selection["summary"] = bucket_summary

    ranked_rows = _attach_investability_to_ranked_rows(
        ranked_response_rows(enriched_ranked),
        investability_gate,
    )
    quarantined_candidates = [
        row
        for row in ranked_rows
        if row.get("strategy_bucket") == UNASSIGNED
        or not row.get("evidence_gate_passed", True)
    ]
    selected_symbols = {
        str(row.get("symbol") or "").upper()
        for row in selected_positions
    }
    winner = next(
        (
            row
            for row in ranked_rows
            if str(row.get("symbol") or "").upper() in selected_symbols
        ),
        {},
    )

    return {
        "allocation_plan": allocation_plan,
        "bucket_selection": bucket_selection,
        "classification_gate": {
            "approved_count": len(selected_positions),
            "quarantine_count": len(quarantined_candidates),
            "quarantined_symbols": [
                row.get("symbol") for row in quarantined_candidates
            ],
            "quarantined_candidates": quarantined_candidates,
            "investability_rejected_count": (
                investability_gate.get("summary") or {}
            ).get("rejected_count", 0),
        },
        "investability_gate": investability_gate,
        "pre_risk_capacity": capacity_selection,
        "pre_risk_capacity_skips": capacity_selection.get("skipped") or [],
        "pre_risk_capacity_promotions": capacity_selection.get("promoted") or [],
        "selected_positions": selected_positions,
        "position_analysis_payloads": position_analysis_payloads,
        "winner": winner,
        "ranked_candidates": ranked_rows,
    }
