from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _unwrap_data(value: Any) -> Any:
    if isinstance(value, Mapping) and "data" in value:
        return value.get("data")
    return value


def _require_success_envelope(name: str, value: Any) -> Any:
    envelope = _dict(value)
    if not envelope:
        raise ValueError(f"{name} response is missing")
    status = str(envelope.get("status") or "").strip().lower()
    if status != "success" or envelope.get("error") not in (None, ""):
        raise ValueError(f"{name} response is not successful")
    return _unwrap_data(envelope)


def normalize_report(report: Mapping[str, Any]) -> dict[str, Any]:
    source = _dict(report)
    broker_mode = str(source.get("broker_mode") or "").strip().upper()
    if broker_mode != "ALPACA":
        raise ValueError("Broker Sync owner snapshots require ALPACA broker mode")

    reconcile = _dict(_require_success_envelope("reconcile", source.get("reconcile")))
    if reconcile.get("ok") is not True:
        raise ValueError("Broker reconcile did not report ok=true")
    database_sync = _dict(reconcile.get("database_sync"))
    if str(database_sync.get("status") or "").strip().lower() != "success":
        raise ValueError("Broker reconcile database sync is not successful")

    sync_status = _dict(
        _require_success_envelope(
            "database_sync_status", source.get("database_sync_status")
        )
    )
    if sync_status.get("has_snapshot") is not True:
        raise ValueError("Database_Agent has no broker snapshot")
    mismatch = _dict(sync_status.get("mismatch"))
    if mismatch.get("is_synced") is not True:
        raise ValueError("Database_Agent does not match the latest broker snapshot")

    broker_snapshot = _dict(source.get("broker_snapshot"))
    account = _dict(
        _require_success_envelope("broker account", broker_snapshot.get("account"))
    )
    positions = _list(
        _require_success_envelope("broker positions", broker_snapshot.get("positions"))
    )
    orders = _list(
        _require_success_envelope("broker orders", broker_snapshot.get("orders"))
    )

    if account.get("paper") is not True:
        raise ValueError("Owner snapshot publishing is restricted to Alpaca Paper accounts")
    if not any(
        account.get(key) is not None for key in ("cash", "equity", "buying_power")
    ):
        raise ValueError("Broker Sync report does not contain account values")

    generated_at = source.get("generated_at")
    if not generated_at:
        raise ValueError("Broker Sync report generated_at is required")

    return {
        "generated_at": generated_at,
        "runtime": {
            "mode": "PAPER",
            "brokerMode": "ALPACA",
            "dryRun": False,
            "liveTradingEnabled": False,
            "flow": "broker_sync_check",
        },
        "cycle": {
            "id": "broker-sync-check",
            "status": "success",
            "marketMode": "BROKER_SYNC",
            "candidateCount": 0,
            "selectedSymbols": [],
            "executionAttempted": False,
            "executionStatus": "not_attempted",
            "executionReason": "read_only_broker_sync",
            "partialFillDetected": False,
        },
        "phases": [
            {
                "name": "preflight",
                "status": "success",
                "message": "Alpaca Paper broker configuration verified.",
            },
            {
                "name": "portfolio_review",
                "status": "success",
                "message": "Latest broker account, positions, and orders loaded.",
            },
            {
                "name": "final_reconciliation",
                "status": "success",
                "message": "Database_Agent matches the latest Alpaca Paper snapshot.",
            },
        ],
        "account": account,
        "positions": positions,
        "openOrders": orders,
        "warnings": [],
        "error": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize Broker Sync Check evidence for secure owner snapshot export."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    normalized = normalize_report(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Normalized Broker Sync owner report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
