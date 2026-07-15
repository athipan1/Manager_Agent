from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse


def _ready(base_url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(
            f"{base_url.rstrip('/')}/ready",
            timeout=timeout,
        ) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    )


@contextmanager
def managed_backtest_agent() -> Iterator[str]:
    """Yield a reachable Backtest_Agent URL, starting a local API when needed."""

    base_url = os.getenv("BACKTEST_AGENT_URL", "http://localhost:8016").rstrip("/")
    if _ready(base_url):
        yield base_url
        return

    if os.getenv("BACKTEST_AGENT_AUTOSTART_LOCAL", "true").strip().lower() not in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }:
        raise RuntimeError(
            f"Backtest_Agent is not ready at {base_url} and local autostart is disabled"
        )

    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError(
            "Local Backtest_Agent autostart is allowed only for an HTTP localhost URL"
        )
    port = parsed.port or 8016
    repo_root = Path(
        os.getenv("BACKTEST_AGENT_REPO", "../Backtest_Agent")
    ).resolve()
    if not (repo_root / "app" / "main.py").exists():
        raise RuntimeError(
            f"Backtest_Agent checkout is unavailable at {repo_root}"
        )

    report_dir = Path(os.getenv("BACKTEST_REPORT_DIR", "reports"))
    report_dir.mkdir(parents=True, exist_ok=True)
    log_path = report_dir / "backtest-agent-api.log"
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        str(repo_root)
        if not existing_pythonpath
        else f"{repo_root}{os.pathsep}{existing_pythonpath}"
    )
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            parsed.hostname,
            "--port",
            str(port),
        ],
        cwd=repo_root,
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + float(
            os.getenv("BACKTEST_AGENT_STARTUP_TIMEOUT_SECONDS", "60")
        )
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "Backtest_Agent exited during startup:\n" + _tail(log_path)
                )
            if _ready(base_url):
                yield base_url
                return
            time.sleep(1)
        raise RuntimeError(
            f"Backtest_Agent did not become ready at {base_url}:\n"
            + _tail(log_path)
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log_handle.close()
