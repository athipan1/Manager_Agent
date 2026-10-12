"""Operator-reviewed, account-scoped external broker holdings.

This registry excludes only known non-AI positions from strategy management.
It never removes positions from broker reconciliation or account-wide exposure.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.hourly_paper_runtime import RuntimeSafetyError

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "unmanaged_broker_holdings.v1.json"


def approved_unmanaged_symbols(account_id: int | str, *, registry_path: Path = REGISTRY_PATH) -> set[str]:
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeSafetyError("Reviewed unmanaged broker position registry is unavailable.") from exc
    if not isinstance(data, dict) or data.get("schema_version") != "unmanaged-broker-holdings.v1":
        raise RuntimeSafetyError("Unmanaged broker registry schema mismatch.")
    if data.get("broker") != "ALPACA_PAPER" or data.get("safety", {}).get("broker_order_mutation_allowed") is not False:
        raise RuntimeSafetyError("Unmanaged broker registry must remain Paper read-only.")
    try:
        registered_account = int(data["account_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeSafetyError("Unmanaged broker registry account ID is invalid.") from exc
    try:
        requested_account = int(account_id)
    except (TypeError, ValueError):
        # Legacy simulation account aliases do not refer to the approved
        # numeric Alpaca Paper account. Never grant them its exemption.
        return set()
    symbols = data.get("symbols")
    if not isinstance(symbols, list) or not symbols or any(
        not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\\-]{0,14}", symbol)
        for symbol in symbols
    ) or len(symbols) != len(set(symbols)):
        raise RuntimeSafetyError("Unmanaged broker registry symbols are invalid.")
    return set(symbols) if registered_account == requested_account else set()


def require_matching_database_scope(database_status: dict, account_id: int | str) -> set[str]:
    """Fail closed if Manager and Database disagree on which holdings are external."""
    expected = approved_unmanaged_symbols(account_id)
    scope = (database_status.get("mismatch") or {}).get("diagnostics") or {}
    bucket_scope = scope.get("strategy_buckets") or {}
    declared = bucket_scope.get("configured_unmanaged_symbols")
    if not isinstance(declared, list) or set(declared) != expected or len(declared) != len(expected):
        raise RuntimeSafetyError("Manager/Database unmanaged position ownership scope is not identical.")
    return expected
