#!/usr/bin/env python3
"""Resolve Backtest runtime settings before the hourly agent stack starts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

API_MINIMUM_BARS = 100
DEFAULT_MINIMUM_BARS = 252
SCHEMA_VERSION = "backtest-runtime-contract.v2"
HOURLY_BACKTEST_MODE = "nested_promotion"
STRATEGY_BUCKET_POLICY_ENABLED = "true"
STRATEGY_BUCKET_REPORT_PATH = "reports/hourly-pre-backtest-discovery.json"
MARKET_CONTEXT_PATH = "reports/hourly-position-review.json"


class BacktestRuntimeContractError(RuntimeError):
    """Raised when the hourly Backtest runtime cannot be made safe."""


def _clean(value: object) -> str:
    return str(value or "").strip()


def resolve_minimum_bars(environ: Mapping[str, str]) -> dict[str, object]:
    """Resolve a repository setting into a Backtest API-compatible value.

    Repository variables are operator-controlled and can drift independently of
    the Backtest API contract. A missing, non-integer, or too-small value is
    replaced with the conservative 252-bar production baseline. Valid values at
    or above the API minimum are preserved.
    """

    source_name = "BACKTEST_MINIMUM_BARS_REQUESTED"
    raw = _clean(environ.get(source_name))
    if not raw:
        source_name = "BACKTEST_MINIMUM_BARS"
        raw = _clean(environ.get(source_name))

    requested: int | None
    reason = "accepted"
    try:
        requested = int(raw) if raw else None
    except ValueError:
        requested = None
        reason = "invalid_integer"

    if requested is None:
        resolved = DEFAULT_MINIMUM_BARS
        if reason == "accepted":
            reason = "missing_value"
    elif requested < API_MINIMUM_BARS:
        resolved = DEFAULT_MINIMUM_BARS
        reason = "below_api_contract_minimum"
    else:
        resolved = requested

    return {
        "schema_version": SCHEMA_VERSION,
        "requested_raw": raw or None,
        "requested": requested,
        "resolved": resolved,
        "api_minimum": API_MINIMUM_BARS,
        "production_default": DEFAULT_MINIMUM_BARS,
        "adjusted": requested != resolved,
        "reason": reason,
        "source": source_name,
    }


def _hourly_policy_contract() -> dict[str, object]:
    """Return immutable production-safe policy settings for Manager hourly runs."""

    return {
        "backtest_mode": HOURLY_BACKTEST_MODE,
        "legacy_fixed_allowed": False,
        "strategy_bucket_aware_enabled": True,
        "strategy_bucket_report_path": STRATEGY_BUCKET_REPORT_PATH,
        "market_context_path": MARKET_CONTEXT_PATH,
        "automatic_strategy_fallback_allowed": False,
    }


def write_runtime_contract(
    *,
    github_env_path: Path,
    report_path: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = os.environ if environ is None else environ
    if not github_env_path:
        raise BacktestRuntimeContractError("GITHUB_ENV path is required.")

    contract = resolve_minimum_bars(env)
    contract.update(_hourly_policy_contract())
    contract["timestamp"] = datetime.now(timezone.utc).isoformat()

    github_env_path.parent.mkdir(parents=True, exist_ok=True)
    with github_env_path.open("a", encoding="utf-8") as handle:
        handle.write(f"BACKTEST_MINIMUM_BARS={contract['resolved']}\n")
        handle.write(f"BACKTEST_MODE={HOURLY_BACKTEST_MODE}\n")
        handle.write(
            f"BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED={STRATEGY_BUCKET_POLICY_ENABLED}\n"
        )
        handle.write(
            f"BACKTEST_STRATEGY_BUCKET_REPORT_PATH={STRATEGY_BUCKET_REPORT_PATH}\n"
        )
        handle.write(f"BACKTEST_MARKET_CONTEXT_PATH={MARKET_CONTEXT_PATH}\n")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(contract, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return contract


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--github-env",
        default=os.getenv("GITHUB_ENV", ""),
        help="GitHub Actions environment file to append.",
    )
    parser.add_argument(
        "--output",
        default="reports/backtest-runtime-contract.json",
        help="JSON audit report path.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    github_env = _clean(args.github_env)
    if not github_env:
        print(
            "Backtest runtime contract failed closed: GITHUB_ENV is missing.",
            file=sys.stderr,
        )
        return 1

    try:
        contract = write_runtime_contract(
            github_env_path=Path(github_env),
            report_path=Path(args.output),
        )
    except (BacktestRuntimeContractError, OSError) as exc:
        print(f"Backtest runtime contract failed closed: {exc}", file=sys.stderr)
        return 1

    print(
        "Resolved Backtest runtime: "
        f"requested_bars={contract['requested_raw']!r}, "
        f"resolved_bars={contract['resolved']}, "
        f"mode={contract['backtest_mode']}, "
        "strategy_bucket_aware=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
