from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_hourly_report_renderer_direct_script_can_import_app(tmp_path):
    repository_root = Path(__file__).resolve().parents[1]
    script = repository_root / "scripts" / "render_hourly_portfolio_report.py"

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    # There is intentionally no reports JSON in tmp_path, so the renderer exits
    # with its normal missing-input status. The regression being guarded is the
    # earlier `ModuleNotFoundError: No module named 'app'` before main() ran.
    assert result.returncode == 1
    assert "missing reports/hourly-auto-trading-report.json" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert "No module named 'app'" not in result.stderr


def test_hourly_report_renderer_runs_without_application_dependencies(tmp_path):
    repository_root = Path(__file__).resolve().parents[1]
    script = repository_root / "scripts" / "render_hourly_portfolio_report.py"

    result = subprocess.run(
        [sys.executable, "-S", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    # ``-S`` excludes site-packages and reproduces the GitHub runner, where the
    # standalone report step does not have FastAPI installed.
    assert result.returncode == 1
    assert "missing reports/hourly-auto-trading-report.json" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert "No module named 'fastapi'" not in result.stderr
