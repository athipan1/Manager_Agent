"""Load the stdlib-only hourly runtime without importing the FastAPI package."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


RUNTIME_PATH = Path(__file__).resolve().parents[1] / "app" / "hourly_paper_runtime.py"
runtime = sys.modules.get("app.hourly_paper_runtime")
if runtime is None:
    SPEC = importlib.util.spec_from_file_location(
        "manager_hourly_paper_runtime",
        RUNTIME_PATH,
    )
    if SPEC is None or SPEC.loader is None:
        raise RuntimeError("Unable to load the hourly Paper runtime module.")
    runtime = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = runtime
    sys.modules["app.hourly_paper_runtime"] = runtime
    SPEC.loader.exec_module(runtime)
