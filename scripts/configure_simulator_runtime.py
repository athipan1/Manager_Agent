#!/usr/bin/env python3
"""Create per-run internal credentials for the isolated Simulator stack.

The generated values exist only in the current GitHub Actions job through
``GITHUB_ENV``. They are not Railway credentials, are never printed, and are
refused outside the manual Simulator dry-run boundary.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import Callable, Mapping


class SimulatorRuntimeError(RuntimeError):
    """Raised when ephemeral Simulator credentials would be unsafe."""


_REQUIRED_BOUNDARY = {
    "TRADING_MODE": "PAPER",
    "BROKER_MODE": "SIMULATOR",
    "DRY_RUN": "true",
    "ALLOW_LIVE_TRADING": "false",
}


def _clean(value: object) -> str:
    return str(value or "").strip()


def validate_simulator_boundary(environ: Mapping[str, str]) -> None:
    """Require a manual, dry-run Simulator context before creating keys."""
    if _clean(environ.get("GITHUB_EVENT_NAME")).lower() == "schedule":
        raise SimulatorRuntimeError(
            "Scheduled runs must use the fail-closed Alpaca Paper path."
        )

    for name, expected in _REQUIRED_BOUNDARY.items():
        actual = _clean(environ.get(name))
        if actual.upper() != expected.upper():
            raise SimulatorRuntimeError(
                f"Simulator runtime requires {name}={expected}."
            )


def _runtime_values(token_factory: Callable[[int], str]) -> dict[str, str]:
    """Return independent high-entropy credentials for local agents only."""
    return {
        "EXECUTION_API_KEY": f"sim-execution-{token_factory(48)}",
        "DATABASE_AGENT_API_KEY": f"sim-database-{token_factory(48)}",
        "PORTFOLIO_AGENT_API_KEY": f"sim-portfolio-{token_factory(48)}",
        "RISK_ADMIN_TOKEN": f"sim-risk-{token_factory(48)}",
        "SIMULATOR_RUNTIME_KEYS_EPHEMERAL": "true",
    }


def configure_simulator_runtime(
    github_env_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    token_factory: Callable[[int], str] = secrets.token_urlsafe,
) -> tuple[str, ...]:
    """Append ephemeral values to ``GITHUB_ENV`` without exposing them."""
    env = os.environ if environ is None else environ
    validate_simulator_boundary(env)

    if not github_env_path:
        raise SimulatorRuntimeError("GITHUB_ENV path is required.")

    values = _runtime_values(token_factory)
    if len(set(values.values())) != len(values):
        raise SimulatorRuntimeError("Generated Simulator credentials are not unique.")

    github_env_path.parent.mkdir(parents=True, exist_ok=True)
    with github_env_path.open("a", encoding="utf-8") as handle:
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise SimulatorRuntimeError(
                    f"Generated value for {name} contains an invalid newline."
                )
            handle.write(f"{name}={value}\n")

    return tuple(values)


def main() -> int:
    github_env = _clean(os.getenv("GITHUB_ENV"))
    if not github_env:
        print("Simulator runtime configuration failed: GITHUB_ENV is missing.", file=sys.stderr)
        return 1

    try:
        names = configure_simulator_runtime(Path(github_env))
    except SimulatorRuntimeError as exc:
        print(f"Simulator runtime configuration failed closed: {exc}", file=sys.stderr)
        return 1

    print(
        "Configured isolated Simulator credentials for this job only: "
        + ", ".join(names)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
