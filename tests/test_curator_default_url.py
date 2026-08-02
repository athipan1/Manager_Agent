from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_curator_default_url_matches_runtime_port() -> None:
    env = os.environ.copy()
    env.pop("CURATOR_AGENT_URL", None)
    env["APP_ENV"] = "development"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app import config; print(config.CURATOR_AGENT_URL)",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "http://curator-agent:8010"
