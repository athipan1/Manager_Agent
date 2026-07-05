from __future__ import annotations

from typing import Any, Dict, List

from app.curator_client import best_effort_curator_signal


def _symbol_from_payload(payload: Dict[str, Any]) -> str:
    return str(payload.get("ticker") or payload.get("symbol") or "").upper()


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
    account_id: str | int = 1,
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

        signal = await _best_effort_signal_with_optional_account(
            symbol=symbol,
            analysis=payload,
            correlation_id=correlation_id,
            account_id=account_id,
        )
        curator_signals.append({"symbol": symbol, **signal})

        updated = dict(payload)
        metadata = dict(updated.get("metadata") or {})
        metadata["curator_signal"] = signal
        updated["metadata"] = metadata
        enriched.append(updated)

    return enriched, curator_signals
