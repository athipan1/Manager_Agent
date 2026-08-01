from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_curator_secret_readiness.py"


def _run(*, execute_key: str = "e" * 48, admin_key: str = "a" * 48) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CURATOR_AGENT_API_KEY"] = execute_key
    env["CURATOR_ADMIN_API_KEY"] = admin_key
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_accepts_distinct_long_secrets() -> None:
    result = _run()

    assert result.returncode == 0, result.stderr
    assert "present, distinct" in result.stdout


def test_rejects_matching_role_secrets() -> None:
    result = _run(execute_key="x" * 48, admin_key="x" * 48)

    assert result.returncode != 0
    assert "must be different" in result.stderr


def test_rejects_short_secret() -> None:
    result = _run(execute_key="short")

    assert result.returncode != 0
    assert "at least 32 characters" in result.stderr
