"""Export reviewed account-scoped Paper holdings to existing local Compose runtime.

The registry is not an authorization to trade: it only labels third-party
holdings as excluded from AI order mutation while preserving broker parity.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "config/unmanaged_broker_holdings.v1.json"


def export_scope(registry_path: Path, account_id: int = 1) -> str:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != "unmanaged-broker-holdings.v1"
        or registry.get("broker") != "ALPACA_PAPER"
        or registry.get("account_id") != account_id
        or not isinstance(registry.get("safety"), dict)
        or registry["safety"].get("read_only") is not True
        or registry["safety"].get("broker_order_mutation_allowed") is not False
    ):
        raise ValueError("Reviewed Paper registry contract mismatch")
    symbols = registry.get("symbols")
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(x, str) or re.fullmatch(r"[A-Z][A-Z0-9.\\-]{0,14}", x) is None for x in symbols)
        or len(symbols) != len(set(symbols))
    ):
        raise ValueError("Invalid reviewed Paper external symbols")
    return json.dumps({str(account_id): sorted(symbols)}, separators=(",", ":"), sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Use the versioned unmanaged Paper symbol registry")
    parser.add_argument("--account-id", type=int, default=1)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    scope = export_scope(args.registry, account_id=args.account_id)
    current = os.getenv("UNMANAGED_BROKER_POSITION_SYMBOLS_JSON")
    if current:
        try:
            same = json.loads(current) == json.loads(scope)
        except json.JSONDecodeError as exc:
            raise SystemExit("Invalid existing external Paper scope") from exc
        if not same:
            raise SystemExit("Refusing mismatched operator-managed Paper scope")
    env_path = os.environ.get("GITHUB_ENV")
    if not env_path:
        raise SystemExit("GITHUB_ENV is required to export the verified Paper scope")
    with Path(env_path).open("a", encoding="utf-8") as handle:
        handle.write("UNMANAGED_BROKER_POSITION_SYMBOLS_JSON=" + scope + "\n")
    print("Validated external Paper scope: account", args.account_id, "symbols", len(json.loads(scope)[str(args.account_id)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
