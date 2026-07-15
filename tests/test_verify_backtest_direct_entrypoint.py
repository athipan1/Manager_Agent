from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_direct_script_context_can_import_walk_forward_runner():
    repository_root = Path(__file__).resolve().parents[1]
    scripts_dir = repository_root / "scripts"
    command = (
        "import verify_backtest_publish as verifier; "
        "from scripts.run_walk_forward_multi_strategy import WALK_FORWARD_ENDPOINT; "
        "assert verifier.REPOSITORY_ROOT == verifier.Path.cwd().parent; "
        "assert WALK_FORWARD_ENDPOINT == '/backtest/multi-strategy/walk-forward'"
    )

    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=scripts_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
