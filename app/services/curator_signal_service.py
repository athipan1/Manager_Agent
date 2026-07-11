from __future__ import annotations

import os
from typing import Any, Dict, List

from app.curator_client import best_effort_curator_signal
from app.curator_ensemble_client import (
    CuratorShadowEnsembleClient,
    validate_shadow_ensemble_contract,
)
from app.resilient_client import AgentUnavailable


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


CURATOR_SHADOW_ENSEMBLE_ENABLED = _env_bool(
    "CURATOR_SHADOW_ENSEMBLE_ENABLED",
    False,
)
CURATOR_SHADOW_ENSEMBLE_REQUIRED = _env_bool(
    "CURATOR_SHADOW_ENSEMBLE_REQUIRED",
    False,
)
CURATOR_SHADOW_ENSEMBLE_MIN_AGREEMENT = _env_float(
    "CURATOR_SHADOW_ENSEMBLE_MIN_AGREEMENT",
    0.60,
)
CURATOR_SHADOW_ENSEMBLE_MAX_SKILLS = _env_int(
    "CURATOR_SHADOW_ENSEMBLE_MAX_SKILLS",
    8,
)


def _symbol_from_payload(payload: Dict[str, Any]) -> str:
    return str(payload.get("ticker") or payload.get("symbol") or "").upper()


def _payload_account_id(payload: Dict[str, Any], fallback: str | int | None) -> str | int:
    """Resolve the account context used for Curator telemetry/recommendations."""
    if fallback is not None:
        return fallback

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    for value in (
        payload.get("account_id"),
        payload.get("account"),
        metadata.get("account_id"),
        metadata.get("account"),
    ):
        if value is not None and value != "":
            return value

    return os.getenv("DEFAULT_ACCOUNT_ID", "1")


async def _best_effort_signal_with_optional_account(
    *,
    symbol: str,
    analysis: Dict[str, Any],
    correlation_id: str,
    account_id: str | int,
) -> Dict[str, Any]:
    try:
        return await best_effort_curator_signal(
            symbol=symbol,
            analysis=analysis,
            correlation_id=correlation_id,
            account_id=account_id,
        )
    except TypeError as exc:
        if "account_id" not in str(exc):
            raise
        return await best_effort_curator_signal(
            symbol=symbol,
            analysis=analysis,
            correlation_id=correlation_id,
        )


async def _shadow_ensemble_signal(
    *,
    symbol: str,
    analysis: Dict[str, Any],
    correlation_id: str,
    account_id: str | int,
) -> Dict[str, Any]:
    inputs = {
        "symbol": symbol,
        "ticker": symbol,
        "analysis": analysis,
        "account_id": account_id,
        "strategy_bucket": analysis.get("strategy_bucket"),
        "market_regime": analysis.get("market_regime") or analysis.get("regime"),
        "final_score": analysis.get("final_score")
        or analysis.get("final_opportunity_score")
        or (analysis.get("score_breakdown") or {}).get("final_opportunity_score"),
    }
    try:
        async with CuratorShadowEnsembleClient() as client:
            data = await client.execute_shadow_ensemble(
                inputs=inputs,
                correlation_id=correlation_id,
                minimum_agreement=CURATOR_SHADOW_ENSEMBLE_MIN_AGREEMENT,
                max_skills=CURATOR_SHADOW_ENSEMBLE_MAX_SKILLS,
            )
        gate = validate_shadow_ensemble_contract(
            data,
            minimum_agreement=CURATOR_SHADOW_ENSEMBLE_MIN_AGREEMENT,
        )
        return {
            "status": "success" if gate["contract_valid"] else "invalid_contract",
            "mode": "shadow_ensemble",
            "ensemble": data,
            "gate": gate,
        }
    except (AgentUnavailable, Exception) as exc:
        return {
            "status": "unavailable",
            "mode": "shadow_ensemble",
            "reason": str(exc),
            "gate": {
                "allowed": False,
                "contract_valid": False,
                "trusted_signal": "hold",
                "consensus_signal": "hold",
                "consensus_state": "unavailable",
                "agreement": None,
                "minimum_agreement": CURATOR_SHADOW_ENSEMBLE_MIN_AGREEMENT,
                "rejection_codes": ["curator_shadow_ensemble_unavailable"],
                "requires_risk_gate": True,
                "direct_execution_allowed": False,
            },
        }


async def enrich_payloads_with_curator_signals(
    *,
    payloads: List[Dict[str, Any]],
    correlation_id: str,
    account_id: str | int | None = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Attach Curator metadata and optionally fail closed before Risk.

    When shadow ensemble is disabled, this preserves the legacy advisory-only
    behavior. When enabled and required, only payloads with a valid Curator
    contract, BUY consensus, and sufficient agreement are returned downstream.
    """
    enriched: List[Dict[str, Any]] = []
    curator_signals: List[Dict[str, Any]] = []

    for payload in payloads or []:
        symbol = _symbol_from_payload(payload)
        if not symbol:
            enriched.append(payload)
            continue

        resolved_account_id = _payload_account_id(payload, account_id)
        if CURATOR_SHADOW_ENSEMBLE_ENABLED:
            signal = await _shadow_ensemble_signal(
                symbol=symbol,
                analysis=payload,
                correlation_id=correlation_id,
                account_id=resolved_account_id,
            )
        else:
            signal = await _best_effort_signal_with_optional_account(
                symbol=symbol,
                analysis=payload,
                correlation_id=correlation_id,
                account_id=resolved_account_id,
            )

        curator_signals.append(
            {"symbol": symbol, "account_id": resolved_account_id, **signal}
        )

        updated = dict(payload)
        metadata = dict(updated.get("metadata") or {})
        metadata["curator_signal"] = signal
        metadata["curator_account_id"] = resolved_account_id
        metadata["curator_shadow_ensemble_enabled"] = (
            CURATOR_SHADOW_ENSEMBLE_ENABLED
        )
        metadata["curator_shadow_ensemble_required"] = (
            CURATOR_SHADOW_ENSEMBLE_REQUIRED
        )
        updated["metadata"] = metadata

        if (
            CURATOR_SHADOW_ENSEMBLE_ENABLED
            and CURATOR_SHADOW_ENSEMBLE_REQUIRED
            and not bool((signal.get("gate") or {}).get("allowed"))
        ):
            continue
        enriched.append(updated)

    return enriched, curator_signals
