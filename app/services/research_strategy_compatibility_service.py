from __future__ import annotations

from typing import Any, Iterable, Mapping

COMPATIBILITY_GATE_SCHEMA = "manager-research-strategy-compatibility.v1"
EXPECTED_BACKTEST_CONTRACT_SCHEMA = "strategy-bucket-compatibility.v1"
DEFAULT_MIN_COMPATIBLE_STRATEGIES = 2


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").strip().upper()


def _bucket(row: Mapping[str, Any]) -> str:
    return str(row.get("strategy_bucket") or row.get("bucket") or "").strip().lower()


def _normalized_families(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(
        dict.fromkeys(
            str(item or "").strip().lower()
            for item in value
            if str(item or "").strip()
        )
    )


def _market_regime_allow_list(market_context: Any) -> tuple[list[str], dict[str, Any]]:
    payload = _mapping(market_context)
    strategy = _mapping(payload.get("market_strategy"))
    gate = _mapping(payload.get("market_regime_gate"))
    tradeable = (
        gate.get("decision") == "PASS"
        and gate.get("new_entries_allowed") is True
        and gate.get("recommended_action") == "trade"
        and strategy.get("recommended_action") == "trade"
    )
    allowed = _normalized_families(strategy.get("allowed_strategies")) if tradeable else []
    return allowed, {
        "tradeable": tradeable,
        "regime": strategy.get("regime"),
        "risk_level": strategy.get("risk_level"),
        "allowed_strategies": allowed,
        "gate_version": gate.get("gate_version"),
    }


def preflight_research_strategy_compatibility(
    ranked_rows: Iterable[Mapping[str, Any]],
    *,
    backtest_contract: Any,
    market_context: Any,
    min_compatible_strategies: int = DEFAULT_MIN_COMPATIBLE_STRATEGIES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Remove only rows proven to have too little strategy diversity.

    Backtest_Agent owns the authoritative bucket mapping. Manager consumes the
    exported readiness contract and intersects it with the same trusted market
    regime allow-list that Backtest will apply later. Unknown/unavailable contract
    evidence is deferred to exact Backtest rather than guessed.
    """

    minimum = max(1, int(min_compatible_strategies))
    rows = [dict(row) for row in ranked_rows if isinstance(row, Mapping)]
    contract = _mapping(backtest_contract)
    contract_schema = str(contract.get("schema_version") or "")
    bucket_families = _mapping(contract.get("bucket_strategy_families"))
    allowed, market = _market_regime_allow_list(market_context)

    contract_valid = (
        contract_schema == EXPECTED_BACKTEST_CONTRACT_SCHEMA
        and bool(bucket_families)
        and contract.get("backtest_remains_authoritative") is True
        and contract.get("thresholds_relaxed") is False
    )
    market_policy_applied = bool(market["tradeable"] and allowed)

    evaluations: list[dict[str, Any]] = []
    rejected_symbols: list[str] = []
    unknown_symbols: list[str] = []
    retained: list[dict[str, Any]] = []

    for row in rows:
        symbol = _symbol(row)
        bucket = _bucket(row)
        bucket_allowed = _normalized_families(bucket_families.get(bucket))

        if not contract_valid:
            status = "unknown_contract"
            compatible = []
            decision = "defer_to_exact_backtest"
            unknown_symbols.append(symbol)
            keep = True
        elif not market_policy_applied:
            # Backtest does not apply its Market Regime candidate override when
            # the trusted market context is not tradeable, so the bucket's full
            # balanced-v1 candidate set remains the exact-run source.
            compatible = list(bucket_allowed)
            if not compatible:
                status = "unknown_bucket"
                decision = "defer_to_exact_backtest"
                unknown_symbols.append(symbol)
                keep = True
            else:
                status = "market_policy_not_applied"
                decision = "eligible_for_exact_backtest"
                keep = True
        elif not bucket_allowed:
            status = "unknown_bucket"
            compatible = []
            decision = "defer_to_exact_backtest"
            unknown_symbols.append(symbol)
            keep = True
        else:
            compatible = [family for family in bucket_allowed if family in allowed]
            if len(compatible) < minimum:
                status = "insufficient_strategy_diversity"
                decision = "exclude_and_backfill"
                rejected_symbols.append(symbol)
                keep = False
            else:
                status = "passed"
                decision = "eligible_for_exact_backtest"
                keep = True

        evidence = {
            "schema_version": COMPATIBILITY_GATE_SCHEMA,
            "symbol": symbol,
            "strategy_bucket": bucket,
            "status": status,
            "bucket_strategy_families": bucket_allowed,
            "market_allowed_strategies": list(allowed),
            "compatible_strategy_families": compatible,
            "compatible_strategy_count": len(compatible),
            "minimum_compatible_strategies": minimum,
            "decision": decision,
            "production_authority_granted": False,
            "risk_execution_authority_granted": False,
            "backtest_thresholds_relaxed": False,
        }
        evaluations.append(evidence)
        if keep:
            enriched = dict(row)
            enriched["pre_backtest_strategy_compatibility"] = evidence
            retained.append(enriched)

    if not contract_valid:
        status = "deferred_contract_unavailable"
    elif not market_policy_applied:
        status = "not_applicable_market_policy"
    elif rejected_symbols:
        status = "completed_with_backfill"
    else:
        status = "completed"

    gate = {
        "schema_version": COMPATIBILITY_GATE_SCHEMA,
        "status": status,
        "backtest_contract_schema": contract_schema or None,
        "backtest_contract_valid": contract_valid,
        "market_regime": market,
        "market_policy_applied": market_policy_applied,
        "minimum_compatible_strategies": minimum,
        "input_count": len(rows),
        "retained_count": len(retained),
        "rejected_symbols": rejected_symbols,
        "unknown_symbols": unknown_symbols,
        "evaluations": evaluations,
        "safety": {
            "production_authority_granted": False,
            "risk_execution_authority_granted": False,
            "unknown_evidence_deferred_to_exact_backtest": True,
            "backtest_thresholds_relaxed": False,
            "backtest_remains_authoritative": True,
        },
    }
    return retained, gate
