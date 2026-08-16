#!/usr/bin/env python3
"""Fail closed when Hourly Backtest stdout and persisted evidence diverge.

The production Backtest command emits a runtime-mode JSON marker followed by the
authoritative Backtest result.  The persisted ``hourly-backtest-result.json`` is
what the downstream trade gate consumes.  These two evidence channels must carry
identical ``data`` payloads; otherwise a verifier, compatibility shim, or other
process may have replaced the result after it was calculated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

NESTED_MODE = "nested_walk_forward_multi_strategy_selection"
SCHEMA_VERSION = "backtest-evidence-coherence.v1"


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_documents(raw: str) -> list[Any]:
    decoder = json.JSONDecoder()
    remaining = raw.strip()
    documents: list[Any] = []
    while remaining:
        try:
            document, offset = decoder.raw_decode(remaining)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Backtest console contains non-JSON content after the runtime marker"
            ) from exc
        documents.append(document)
        remaining = remaining[offset:].lstrip()
    return documents


def load_authoritative_console_result(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Backtest console does not exist: {path}")
    documents = _json_documents(path.read_text(encoding="utf-8"))
    for document in reversed(documents):
        if isinstance(document, dict) and isinstance(document.get("data"), dict):
            return document
    raise ValueError("Backtest console contains no result payload")


def load_persisted_result(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Persisted Backtest result does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("Persisted Backtest result has no data payload")
    return payload


def verify_evidence_coherence(
    console_result: dict[str, Any],
    persisted_result: dict[str, Any],
) -> dict[str, Any]:
    console_data = console_result["data"]
    persisted_data = persisted_result["data"]
    console_mode = console_data.get("mode")
    persisted_mode = persisted_data.get("mode")
    console_digest = _canonical_digest(console_data)
    persisted_digest = _canonical_digest(persisted_data)
    coherent = (
        console_mode == NESTED_MODE
        and persisted_mode == NESTED_MODE
        and console_digest == persisted_digest
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if coherent else "fail",
        "coherent": coherent,
        "console_mode": console_mode,
        "persisted_mode": persisted_mode,
        "console_data_sha256": console_digest,
        "persisted_data_sha256": persisted_digest,
        "safety": {
            "trade_gate_may_consume_persisted_result": coherent,
            "broker_mutation_allowed_by_this_check": False,
        },
    }
    if not coherent:
        reasons: list[str] = []
        if console_mode != NESTED_MODE:
            reasons.append("console_not_nested_production_evidence")
        if persisted_mode != NESTED_MODE:
            reasons.append("persisted_not_nested_production_evidence")
        if console_digest != persisted_digest:
            reasons.append("console_and_persisted_data_diverged")
        report["reasons"] = reasons
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--console",
        type=Path,
        default=Path("reports/hourly-backtest-console.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/hourly-backtest-result.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/hourly-backtest-evidence-coherence.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        console_result = load_authoritative_console_result(args.console)
        persisted_result = load_persisted_result(args.report)
        result = verify_evidence_coherence(console_result, persisted_result)
    except (ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "fail",
            "coherent": False,
            "reasons": ["evidence_unreadable"],
            "error": str(exc),
            "safety": {
                "trade_gate_may_consume_persisted_result": False,
                "broker_mutation_allowed_by_this_check": False,
            },
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("coherent") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
