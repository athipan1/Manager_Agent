from pathlib import Path
import subprocess
import sys


def test_hourly_trade_gate_script_imports_when_executed_directly() -> None:
    script = Path("scripts/resolve_hourly_trade_gate.py")
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--challenger-output" in completed.stdout
