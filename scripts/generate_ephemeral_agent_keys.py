#!/usr/bin/env python3
"""Generate per-run internal API keys and export them to GitHub Actions.

The generated values are shared by the Manager process and the corresponding
locally started agent containers for this workflow run only. Values are masked
immediately and never written to repository files or artifacts.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

KEY_NAMES = (
    "PORTFOLIO_AGENT_API_KEY",
    "PROFIT_AGENT_API_KEY",
)


def _write_github_env(values: dict[str, str]) -> None:
    env_path = os.getenv("GITHUB_ENV", "").strip()
    if not env_path:
        raise RuntimeError("GITHUB_ENV is required")
    with Path(env_path).open("a", encoding="utf-8") as handle:
        for name, value in values.items():
            handle.write(f"{name}={value}\n")


def main() -> int:
    values = {name: secrets.token_urlsafe(48) for name in KEY_NAMES}
    for value in values.values():
        print(f"::add-mask::{value}")
    _write_github_env(values)
    print("Generated ephemeral internal agent API keys for this workflow run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
