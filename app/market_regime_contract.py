from __future__ import annotations

from typing import Any, Iterable


MARKET_REGIME_SCHEMA_VERSION = "1.1"
MARKET_REGIME_GATE_VERSION = "manager-market-regime-gate.v1"
MULTIPLIER_FIELDS = (
    "position_size_multiplier",
    "risk_multiplier",
    "risk_budget_multiplier",
    "exposure_cap",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def market_regime_envelope_issues(
    response: Any,
    correlation_id: str,
) -> list[str]:
    """Return contract issues without discarding usable advisory data."""
    payload = _as_dict(response)
    issues: list[str] = []
    if payload.get("status") != "success":
        issues.append("market_regime_response_not_success")
    if payload.get("agent_type") != "market-regime-agent":
        issues.append("market_regime_agent_type_mismatch")
    if str(payload.get("schema_version") or "") != MARKET_REGIME_SCHEMA_VERSION:
        issues.append("market_regime_schema_version_mismatch")
    response_correlation_id = payload.get("correlation_id")
    if response_correlation_id not in {None, "", correlation_id}:
        issues.append("market_regime_correlation_id_mismatch")
    if not isinstance(payload.get("data"), dict):
        issues.append("market_regime_data_missing")
    return issues


def evaluate_market_regime_gate(
    regime: Any,
    strategy: Any,
    *,
    contract_issues: Iterable[str] = (),
) -> dict[str, Any]:
    """Decide whether Market Regime evidence permits opening new positions.

    Existing-position monitoring is deliberately outside this gate. A malformed,
    deprecated, REVIEW or NO_TRADE contract fails closed only for new entries.
    """
    regime_data = _as_dict(regime)
    strategy_data = _as_dict(strategy)
    reasons = list(dict.fromkeys(str(item) for item in contract_issues if item))
    warnings: list[str] = []

    quality = _as_dict(strategy_data.get("data_quality")) or _as_dict(
        regime_data.get("data_quality")
    )
    if not quality:
        reasons.append("market_regime_data_quality_missing")
    else:
        quality_status = str(quality.get("status") or "").strip().lower()
        if quality.get("trade_allowed") is not True:
            reasons.append("market_regime_data_quality_blocks_trade")
        if quality_status == "blocked":
            reasons.append("market_regime_data_quality_blocked")
        elif quality_status == "review":
            warnings.append("market_regime_data_quality_review")
        elif quality_status != "good":
            reasons.append("market_regime_data_quality_status_invalid")

    action = str(strategy_data.get("recommended_action") or "").strip().lower()
    if action != "trade":
        if action == "no_trade":
            reasons.append("market_regime_recommended_no_trade")
        elif action == "review":
            reasons.append("market_regime_recommended_review")
        else:
            reasons.append("market_regime_recommended_action_missing_or_invalid")

    allowed = [
        str(item).strip().lower()
        for item in (strategy_data.get("allowed_strategies") or [])
        if str(item).strip()
    ]
    recommended = str(strategy_data.get("recommended_strategy") or "").strip().lower()
    if action == "trade":
        if not allowed:
            reasons.append("market_regime_allowed_strategies_empty")
        elif recommended not in allowed:
            reasons.append("market_regime_recommended_strategy_not_allowed")

        for field in MULTIPLIER_FIELDS:
            try:
                value = float(strategy_data.get(field))
            except (TypeError, ValueError):
                reasons.append(f"market_regime_{field}_invalid")
                continue
            if value <= 0:
                reasons.append(f"market_regime_{field}_not_positive")

    reasons = list(dict.fromkeys(reasons))
    if not reasons:
        decision = "PASS"
    elif action == "no_trade" and reasons == ["market_regime_recommended_no_trade"]:
        decision = "NO_TRADE"
    else:
        decision = "REVIEW"

    return {
        "gate_version": MARKET_REGIME_GATE_VERSION,
        "new_entries_allowed": not reasons,
        "decision": decision,
        "recommended_action": action or None,
        "recommended_strategy": recommended or None,
        "data_quality_status": str(quality.get("status") or "").lower() or None,
        "data_quality_trade_allowed": quality.get("trade_allowed") if quality else None,
        "reasons": reasons,
        "warnings": warnings,
    }
