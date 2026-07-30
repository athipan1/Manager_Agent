import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_builder_runs_directly_without_pythonpath(tmp_path):
    output = tmp_path / "hourly-auto-trading-report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_hourly_operator_artifact.py"),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["runtime"]["liveTradingEnabled"] is False
    assert payload["cycle"]["executionStatus"] == "not_attempted"
