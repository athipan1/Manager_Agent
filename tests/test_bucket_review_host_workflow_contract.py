"""Contract for running Bucket Profit Review in the GitHub Actions host process.

The services run inside Docker, but the review scripts run on the Actions host.
Keep app imports and pinned dependencies available without relaxing safety gates.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "bucket-profit-review.yml"


def test_bucket_workflow_has_pinned_host_dependencies_and_import_path():
    contents = WORKFLOW.read_text(encoding="utf-8")

    assert "PYTHONPATH: ${{ github.workspace }}/Manager_Agent" in contents
    assert "python -m pip install --disable-pip-version-check -r requirements.prod.base.txt" in contents
    assert 'python-version: "3.11"' in contents

    # This reporting workflow must never submit real/live orders.
    assert "TRADING_MODE: PAPER" in contents
    assert 'ALLOW_LIVE_TRADING: "false"' in contents
    assert 'DRY_RUN: "true"' in contents


def test_bucket_review_cli_imports_with_host_working_directory():
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "scripts/bucket_profit_review.py", "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--bucket" in result.stdout
