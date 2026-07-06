from __future__ import annotations

import os
from typing import Any, Dict, List

from app.curator_client import best_effort_curator_signal


def _symbol_from_payload(payload: Dict[str, Any]) -> str:
    return str(payload.get("ticker") or payload.get("symbol") or "").upper()


def _payload_account_id(payload: Dict[str, Any], fallback: str | int | None) -> str | int:
    """Resolve the account context used for Curator telemetry/recommendations.

    Discovery should pass the request account_id explicitly. This helper also
    accepts payload-level account hints for older call sites and falls back to
    DEFAULT_ACCOUNT_ID instead of hard-coding account 1.
    """
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


async def enrich_payloads_with_curator_signals(
    *,
    payloads: List[Dict[str, Any]],
    correlation_id: str,
    account_id: str | int | None = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Attach Curator signal metadata to selected payloads without changing decisions.

    Curator output is deliberately advisory in this phase. Risk approval,
    sizing, and execution still use the existing Manager/Risk/Execution path.
    """
    enriched: List[Dict[str, Any]] = []
    curator_signals: List[Dict[str, Any]] = []

    for payload in payloads or []:
        symbol = _symbol_from_payload(payload)
        if not symbol:
            enriched.append(payload)
            continue

        resolved_account_id = _payload_account_id(payload, account_id)
        signal = await _best_effort_signal_with_optional_account(
            symbol=symbol,
            analysis=payload,
            correlation_id=correlation_id,
            account_id=resolved_account_id,
        )
        curator_signals.append({"symbol": symbol, "account_id": resolved_account_id, **signal})

        updated = dict(payload)
        metadata = dict(updated.get("metadata") or {})
        metadata["curator_signal"] = signal
        metadata["curator_account_id"] = resolved_account_id
        updated["metadata"] = metadata
        enriched.append(updated)

    return enriched, curator_signals
