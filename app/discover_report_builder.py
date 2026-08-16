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
                "investability_fallback_promoted": bool(
                    selected_row.get("investability_fallback_promoted")
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
            "investability_fallback_promoted": position.get(
                "investability_fallback_promoted"
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


def _candidate_count(bucket_selection: Dict[str, Any]) -> int:
    symbols: set[str] = set()
    for bucket_name, payload in bucket_selection.items():
        if bucket_name == "summary" or not isinstance(payload, Mapping):
            continue
        for key in ("selected", "overflow"):
            for row in payload.get(key) or []:
                if not isinstance(row, Mapping):
                    continue
                symbol = str(row.get("symbol") or "").strip().upper()
                if symbol:
                    symbols.add(symbol)
    return len(symbols)


def _exclude_investability_rejections(
    bucket_selection: Dict[str, Any],
    rejected_symbols: set[str],
) -> Dict[str, Any]:
    """Remove only candidates already rejected by the unchanged Investability gate."""

    rejected = {str(symbol).upper() for symbol in rejected_symbols if symbol}
    adjusted: Dict[str, Any] = {}
    for bucket_name, payload in bucket_selection.items():
        if bucket_name == "summary" or not isinstance(payload, Mapping):
            adjusted[bucket_name] = dict(payload) if isinstance(payload, Mapping) else payload
            continue
        next_payload = dict(payload)
        excluded_count = 0
        for key in ("selected", "overflow"):
            rows: List[Dict[str, Any]] = []
            for row in payload.get(key) or []:
                if not isinstance(row, Mapping):
                    continue
                symbol = str(row.get("symbol") or "").upper()
                if symbol in rejected:
                    excluded_count += 1
                    continue
                rows.append(dict(row))
            next_payload[key] = rows
        next_payload["selected_count"] = len(next_payload.get("selected") or [])
        next_payload["investability_excluded_count"] = excluded_count
        adjusted[bucket_name] = next_payload

    summary = dict(adjusted.get("summary") or {})
    summary["investability_excluded_symbols"] = sorted(rejected)
    summary["investability_excluded_count"] = len(rejected)
    adjusted["summary"] = summary
    return adjusted


def _mark_investability_fallbacks(
    *,
    capacity_selection: Dict[str, Any],
    selected_positions: List[Dict[str, Any]],
    position_analysis_payloads: List[Dict[str, Any]],
    initial_selected_symbols: set[str],
) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    final_symbols = {
        str(row.get("symbol") or "").upper()
        for row in selected_positions
        if row.get("symbol")
    }
    promoted_symbols = sorted(final_symbols - initial_selected_symbols)
    promoted_set = set(promoted_symbols)
    if not promoted_set:
        return (
            capacity_selection,
            selected_positions,
            position_analysis_payloads,
            promoted_symbols,
        )

    next_capacity = dict(capacity_selection)
    next_bucket_selection = dict(next_capacity.get("bucket_selection") or {})
    for bucket_name, payload in list(next_bucket_selection.items()):
        if bucket_name == "summary" or not isinstance(payload, Mapping):
            continue
        next_payload = dict(payload)
        next_rows = []
        for row in payload.get("selected") or []:
            next_row = dict(row)
            symbol = str(next_row.get("symbol") or "").upper()
            if symbol in promoted_set:
                next_row["investability_fallback_promoted"] = True
            next_rows.append(next_row)
        next_payload["selected"] = next_rows
        next_bucket_selection[bucket_name] = next_payload
    summary = dict(next_bucket_selection.get("summary") or {})
    summary["investability_fallback_promoted_count"] = len(promoted_symbols)
    summary["investability_fallback_promoted_symbols"] = promoted_symbols
    next_bucket_selection["summary"] = summary
    next_capacity["bucket_selection"] = next_bucket_selection

    next_positions: List[Dict[str, Any]] = []
    for row in selected_positions:
        next_row = dict(row)
        if str(next_row.get("symbol") or "").upper() in promoted_set:
            next_row["investability_fallback_promoted"] = True
        next_positions.append(next_row)

    next_payloads: List[Dict[str, Any]] = []
    for row in position_analysis_payloads:
        next_row = dict(row)
        symbol = str(next_row.get("ticker") or next_row.get("symbol") or "").upper()
        if symbol in promoted_set:
            next_row["investability_fallback_promoted"] = True
            portfolio_context = dict(next_row.get("portfolio_context") or {})
            portfolio_context["investability_fallback_promoted"] = True
            next_row["portfolio_context"] = portfolio_context
        next_payloads.append(next_row)

    return next_capacity, next_positions, next_payloads, promoted_symbols


def _combine_investability_attempts(
    *,
    attempts: List[Dict[str, Any]],
    final_gate: Dict[str, Any],
    promoted_symbols: List[str],
) -> Dict[str, Any]:
    decisions_by_symbol: Dict[str, Dict[str, Any]] = {}
    for gate in attempts:
        for decision in gate.get("decisions") or []:
            if not isinstance(decision, Mapping):
                continue
            symbol = str(decision.get("symbol") or "").upper()
            if symbol:
                decisions_by_symbol[symbol] = dict(decision)

    decisions = list(decisions_by_symbol.values())
    rejected = [row for row in decisions if not row.get("allowed")]
    combined = dict(final_gate)
    combined["decisions"] = decisions
    combined["rejected"] = rejected
    combined["attempt_count"] = len(attempts)
    combined["fallback_promoted_count"] = len(promoted_symbols)
    combined["fallback_promoted_symbols"] = promoted_symbols
    combined["summary"] = {
        "candidate_count": len(decisions),
        "allowed_count": sum(bool(row.get("allowed")) for row in decisions),
        "rejected_count": len(rejected),
        "blocked_count": sum(row.get("status") == "block" for row in decisions),
        "quarantined_count": sum(
            row.get("status") == "quarantine" for row in decisions
        ),
        "warning_count": sum(bool(row.get("warning_codes")) for row in decisions),
        "final_selected_count": len(final_gate.get("selected_positions") or []),
        "fallback_promoted_count": len(promoted_symbols),
    }
    return combined


def _capacity_investability_with_safe_backfill(
    *,
    enriched_ranked: List[Dict[str, Any]],
    allocation_plan: Dict[str, Any],
    base_bucket_selection: Dict[str, Any],
    positions: List[Any],
    portfolio_value: Any,
    minimum_incremental_value: Any,
) -> Dict[str, Any]:
    """Re-run capacity after Investability rejects a selected candidate.

    The retry pool is never expanded. It consists only of same-bucket candidates
    already produced by select_candidates_by_bucket, so score, classification,
    evidence and bucket limits remain unchanged. Every promoted fallback is
    re-checked by the same Investability gate before it can reach Backtest.
    """

    rejected_symbols: set[str] = set()
    attempts: List[Dict[str, Any]] = []
    capacity_attempts: List[Dict[str, Any]] = []
    initial_selected_symbols: set[str] = set()
    initial_selected_count = 0
    final_capacity: Dict[str, Any] = {}
    final_gate: Dict[str, Any] = {
        "selected_positions": [],
        "position_analysis_payloads": [],
        "decisions": [],
        "rejected": [],
        "summary": {},
    }
    max_attempts = max(1, _candidate_count(base_bucket_selection) + 1)

    for attempt_number in range(1, max_attempts + 1):
        retry_selection = _exclude_investability_rejections(
            base_bucket_selection,
            rejected_symbols,
        )
        capacity_selection = apply_pre_risk_capacity_selection(
            ranked=enriched_ranked,
            allocation_plan=allocation_plan,
            bucket_selection=retry_selection,
            positions=positions,
            portfolio_value=portfolio_value,
            minimum_incremental_value=minimum_incremental_value,
        )
        capacity_bucket_selection = capacity_selection["bucket_selection"]
        selected_before_gate = build_selected_positions(
            ranked=enriched_ranked,
            allocation_plan=allocation_plan,
            bucket_selection=capacity_bucket_selection,
        )
        if attempt_number == 1:
            initial_selected_count = len(selected_before_gate)
            initial_selected_symbols = {
                str(row.get("symbol") or "").upper()
                for row in selected_before_gate
                if row.get("symbol")
            }
        payloads_before_gate = build_position_analysis_payloads(
            ranked=enriched_ranked,
            selected_positions=selected_before_gate,
        )
        gate = _investability_filter(
            selected_positions=selected_before_gate,
            position_analysis_payloads=payloads_before_gate,
        )
        attempts.append(gate)
        capacity_attempts.append(
            {
                "attempt": attempt_number,
                "excluded_symbols": sorted(rejected_symbols),
                "capacity_selected_symbols": [
                    row.get("symbol") for row in selected_before_gate
                ],
                "investability_rejected_symbols": [
                    row.get("symbol") for row in gate.get("rejected") or []
                ],
            }
        )
        final_capacity = capacity_selection
        final_gate = gate

        current_rejections = {
            str(row.get("symbol") or "").upper()
            for row in gate.get("rejected") or []
            if row.get("symbol")
        }
        new_rejections = current_rejections - rejected_symbols
        if not new_rejections:
            break
        rejected_symbols.update(new_rejections)

    final_capacity, selected_positions, position_analysis_payloads, promoted_symbols = (
        _mark_investability_fallbacks(
            capacity_selection=final_capacity,
            selected_positions=list(final_gate.get("selected_positions") or []),
            position_analysis_payloads=list(
                final_gate.get("position_analysis_payloads") or []
            ),
            initial_selected_symbols=initial_selected_symbols,
        )
    )
    final_gate = dict(final_gate)
    final_gate["selected_positions"] = selected_positions
    final_gate["position_analysis_payloads"] = position_analysis_payloads
    combined_gate = _combine_investability_attempts(
        attempts=attempts,
        final_gate=final_gate,
        promoted_symbols=promoted_symbols,
    )

    return {
        "capacity_selection": final_capacity,
        "investability_gate": combined_gate,
        "selected_positions": selected_positions,
        "position_analysis_payloads": position_analysis_payloads,
        "initial_selected_count": initial_selected_count,
        "initial_selected_symbols": sorted(initial_selected_symbols),
        "rejected_symbols": sorted(rejected_symbols),
        "fallback_promoted_symbols": promoted_symbols,
        "attempts": capacity_attempts,
    }


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
    base_bucket_selection = select_candidates_by_bucket(
        enriched_ranked,
        min_final_score=min_final_score,
    )
    guarded_selection = _capacity_investability_with_safe_backfill(
        enriched_ranked=enriched_ranked,
        allocation_plan=allocation_plan,
        base_bucket_selection=base_bucket_selection,
        positions=list(positions or []),
        portfolio_value=portfolio_value,
        minimum_incremental_value=minimum_incremental_value,
    )
    capacity_selection = guarded_selection["capacity_selection"]
    bucket_selection = capacity_selection["bucket_selection"]
    investability_gate = guarded_selection["investability_gate"]
    selected_positions = guarded_selection["selected_positions"]
    position_analysis_payloads = guarded_selection[
        "position_analysis_payloads"
    ]

    allocation_plan = dict(allocation_plan)
    allocation_plan["investability_gate"] = investability_gate
    allocation_plan["investability_fallback"] = {
        "attempts": guarded_selection["attempts"],
        "initial_selected_symbols": guarded_selection[
            "initial_selected_symbols"
        ],
        "rejected_symbols": guarded_selection["rejected_symbols"],
        "promoted_symbols": guarded_selection[
            "fallback_promoted_symbols"
        ],
        "retry_pool_expanded": False,
        "thresholds_relaxed": False,
    }
    bucket_selection = dict(bucket_selection)
    bucket_summary = dict(bucket_selection.get("summary") or {})
    bucket_summary.update(
        {
            "selected_before_investability": guarded_selection[
                "initial_selected_count"
            ],
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
            "investability_attempt_count": investability_gate.get(
                "attempt_count", 1
            ),
            "investability_fallback_promoted_count": len(
                guarded_selection["fallback_promoted_symbols"]
            ),
            "investability_fallback_promoted_symbols": guarded_selection[
                "fallback_promoted_symbols"
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
            "investability_fallback_promoted_count": len(
                guarded_selection["fallback_promoted_symbols"]
            ),
        },
        "investability_gate": investability_gate,
        "investability_fallback": allocation_plan["investability_fallback"],
        "pre_risk_capacity": capacity_selection,
        "pre_risk_capacity_skips": capacity_selection.get("skipped") or [],
        "pre_risk_capacity_promotions": capacity_selection.get("promoted") or [],
        "selected_positions": selected_positions,
        "position_analysis_payloads": position_analysis_payloads,
        "winner": winner,
        "ranked_candidates": ranked_rows,
    }