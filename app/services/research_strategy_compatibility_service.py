from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping

COMPATIBILITY_GATE_SCHEMA = "manager-research-strategy-compatibility.v1"
EXPECTED_BACKTEST_CONTRACT_SCHEMA = "strategy-bucket-compatibility.v1"
DEFAULT_MIN_COMPATIBLE_STRATEGIES = 1
DEFAULT_MARKET_CONTEXT_PATH = Path("reports/hourly-position-review.json")
DEFAULT_BACKTEST_READY_URL = "http://localhost:8016/ready"


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


def _runtime_minimum() -> int:
    raw = str(
        os.getenv(
            "BACKTEST_RESEARCH_MIN_COMPATIBLE_STRATEGIES",
            str(DEFAULT_MIN_COMPATIBLE_STRATEGIES),
        )
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MIN_COMPATIBLE_STRATEGIES
    return max(1, min(value, 25))


def load_runtime_market_context() -> tuple[dict[str, Any], dict[str, Any]]:
    configured = str(os.getenv("BACKTEST_MARKET_CONTEXT_PATH") or "").strip()
    path = Path(configured) if configured else DEFAULT_MARKET_CONTEXT_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, {"status": "unavailable", "source": str(path), "reason": "missing_file"}
    except (OSError, json.JSONDecodeError) as exc:
        return {}, {
            "status": "unavailable",
            "source": str(path),
            "reason": type(exc).__name__,
        }
    if not isinstance(payload, dict):
        return {}, {"status": "unavailable", "source": str(path), "reason": "invalid_root"}
    return payload, {"status": "loaded", "source": str(path), "reason": None}


def load_runtime_backtest_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    url = str(os.getenv("BACKTEST_READINESS_URL") or DEFAULT_BACKTEST_READY_URL).strip()
    try:
        timeout = float(os.getenv("BACKTEST_COMPATIBILITY_PREFLIGHT_TIMEOUT_SECONDS", "3"))
    except ValueError:
        timeout = 3.0
    timeout = max(0.25, min(timeout, 10.0))
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        TimeoutError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        ConnectionResetError,
        json.JSONDecodeError,
    ) as exc:
        return {}, {
            "status": "unavailable",
            "source": url,
            "reason": type(exc).__name__,
        }
    if not isinstance(payload, dict):
        return {}, {"status": "unavailable", "source": url, "reason": "invalid_root"}
    data = _mapping(payload.get("data"))
    contract = data.get("strategy_bucket_compatibility")
    if not isinstance(contract, Mapping):
        return {}, {
            "status": "unavailable",
            "source": url,
            "reason": "compatibility_contract_missing",
        }
    return dict(contract), {"status": "loaded", "source": url, "reason": None}


def preflight_research_strategy_compatibility(
    ranked_rows: Iterable[Mapping[str, Any]],
    *,
    backtest_contract: Any,
    market_context: Any,
    min_compatible_strategies: int = DEFAULT_MIN_COMPATIBLE_STRATEGIES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Remove only rows with no usable exact-Backtest strategy intersection.

    Backtest_Agent owns the authoritative bucket mapping and later applies the
    same per-symbol bucket plus Market Regime intersection to the actual balanced-v1
    candidate set. Manager therefore needs only one trusted compatible family to
    justify spending an exact Backtest slot. This is admission-only evidence: it
    never authorizes production entry, Risk, Execution or broker mutation, and it
    does not change any Backtest validation or promotion threshold.
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
            "admission_only": True,
            "exact_backtest_required": True,
            "compatible_strategy_families_are_allowlist": True,
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
        "rejected_count": len(rejected_symbols),
        "rejected_symbols": rejected_symbols,
        "unknown_count": len(unknown_symbols),
        "unknown_symbols": unknown_symbols,
        "evaluations": evaluations,
        "admission_policy": {
            "at_least_one_compatible_strategy_required": minimum == 1,
            "exact_backtest_required": True,
            "compatible_strategy_families_are_allowlist": True,
            "production_binding": False,
            "thresholds_relaxed": False,
        },
        "safety": {
            "production_authority_granted": False,
            "risk_execution_authority_granted": False,
            "unknown_evidence_deferred_to_exact_backtest": True,
            "backtest_thresholds_relaxed": False,
            "backtest_remains_authoritative": True,
        },
    }
    return retained, gate


def preflight_runtime_research_strategy_compatibility(
    ranked_rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load runtime evidence and apply the compatibility preflight when possible."""

    market_context, market_source = load_runtime_market_context()
    # Avoid a network dependency when the exact Backtest Market Regime policy would
    # not apply anyway. This keeps unit tests and non-hourly paths deterministic.
    allowed, market = _market_regime_allow_list(market_context)
    if not market.get("tradeable") or not allowed:
        retained, gate = preflight_research_strategy_compatibility(
            ranked_rows,
            backtest_contract={},
            market_context=market_context,
            min_compatible_strategies=_runtime_minimum(),
        )
        gate["runtime_sources"] = {
            "market_context": market_source,
            "backtest_contract": {
                "status": "not_requested",
                "source": None,
                "reason": "market_policy_not_applied",
            },
        }
        # Contract is unnecessary when Backtest will not apply the regime override.
        # Preserve every row rather than label them unknown because the bucket-only
        # candidate set remains authoritative for the exact run.
        gate["status"] = "not_applicable_market_policy"
        return [dict(row) for row in ranked_rows if isinstance(row, Mapping)], gate

    contract, contract_source = load_runtime_backtest_contract()
    retained, gate = preflight_research_strategy_compatibility(
        ranked_rows,
        backtest_contract=contract,
        market_context=market_context,
        min_compatible_strategies=_runtime_minimum(),
    )
    gate["runtime_sources"] = {
        "market_context": market_source,
        "backtest_contract": contract_source,
    }
    return retained, gate