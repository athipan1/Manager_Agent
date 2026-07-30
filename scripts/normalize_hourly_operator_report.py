#!/usr/bin/env python3
"""Normalize legacy operator artifacts before exporting the public dashboard snapshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

VALID_MODES = {"PAPER", "SIMULATOR"}


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def normalize_report(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = as_dict(report)
    runtime = as_dict(payload.get("runtime"))
    raw_mode = str(runtime.get("mode") or payload.get("mode") or "").upper()
    if raw_mode == "ALPACA_PAPER":
        raw_mode = "PAPER"
    broker = str(
        runtime.get("brokerMode")
        or runtime.get("broker_mode")
        or payload.get("broker_mode")
        or ""
    ).upper()
    dry_run = runtime.get("dryRun", runtime.get("dry_run"))
    if raw_mode not in VALID_MODES:
        raw_mode = "PAPER" if broker == "ALPACA" and dry_run is False else "SIMULATOR"
    if raw_mode == "PAPER":
        broker = "ALPACA"
        dry_run = False
    else:
        broker = broker if broker in {"ALPACA", "SIMULATOR"} else "SIMULATOR"
        dry_run = True
    payload["mode"] = raw_mode
    payload["broker_mode"] = broker
    payload["runtime"] = {
        **runtime,
        "mode": raw_mode,
        "brokerMode": broker,
        "dryRun": bool(dry_run),
        "liveTradingEnabled": False,
        "flow": runtime.get("flow") or payload.get("flow") or "hourly_portfolio_cycle",
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Operator artifact is missing or invalid: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Operator artifact must contain a JSON object")
    output = args.output or args.input
    normalized = normalize_report(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        "Normalized hourly operator artifact: "
        f"mode={normalized['runtime']['mode']} "
        f"broker={normalized['runtime']['brokerMode']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
