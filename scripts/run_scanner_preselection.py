from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


class ScannerPreselectionRequestError(RuntimeError):
    """Raised when Manager preselection cannot complete within its budget."""

    def __init__(
        self,
        message: str,
        *,
        attempts_used: int,
        errors: List[Dict[str, Any]],
    ) -> None:
        super().__init__(message)
        self.attempts_used = attempts_used
        self.errors = errors


def _request_json(
    url: str,
    payload: Dict[str, Any],
    *,
    attempt_timeout: int,
    deadline_seconds: int,
    max_attempts: int,
    retry_delay_seconds: float,
) -> Tuple[Dict[str, Any], int]:
    started_at = time.monotonic()
    errors: List[Dict[str, Any]] = []

    for attempt in range(1, max_attempts + 1):
        elapsed = time.monotonic() - started_at
        remaining = deadline_seconds - elapsed
        if remaining <= 1:
            break

        timeout = max(1, min(attempt_timeout, int(remaining)))
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8")), attempt
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            errors.append(
                {
                    "attempt": attempt,
                    "timeout_seconds": timeout,
                    "error_type": type(exc).__name__,
                    "http_status": exc.code,
                    "error": body,
                }
            )
            retryable = exc.code == 429 or exc.code >= 500
            if not retryable:
                raise ScannerPreselectionRequestError(
                    f"Scanner preselection returned HTTP {exc.code}: {body}",
                    attempts_used=attempt,
                    errors=errors,
                ) from exc
        except (
            TimeoutError,
            socket.timeout,
            urllib.error.URLError,
            ConnectionResetError,
        ) as exc:
            errors.append(
                {
                    "attempt": attempt,
                    "timeout_seconds": timeout,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

        elapsed = time.monotonic() - started_at
        remaining = deadline_seconds - elapsed
        if attempt >= max_attempts or remaining <= 1:
            break

        delay = min(retry_delay_seconds * attempt, max(0.0, remaining - 1))
        if delay > 0:
            print(
                "Scanner preselection transient failure; "
                f"retrying attempt {attempt + 1}/{max_attempts} "
                f"after {delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(delay)

    attempts_used = len(errors)
    last_error = errors[-1] if errors else {}
    raise ScannerPreselectionRequestError(
        "Scanner preselection exhausted its bounded request budget: "
        f"attempts={attempts_used}, deadline_seconds={deadline_seconds}, "
        f"last_error={last_error.get('error_type', 'deadline_exhausted')}: "
        f"{last_error.get('error', '-')}",
        attempts_used=attempts_used,
        errors=errors,
    )


def extract_backtest_symbols(response: Dict[str, Any]) -> List[str]:
    if response.get("status") != "success":
        raise ValueError(f"Scanner preselection failed: {response}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise ValueError("Scanner preselection response has no data object")
    positions = data.get("pre_backtest_selected_positions") or []
    return list(
        dict.fromkeys(
            str(item.get("symbol") or item.get("ticker") or "").upper()
            for item in positions
            if isinstance(item, dict)
            and str(item.get("symbol") or item.get("ticker") or "").strip()
        )
    )


def _payload_from_env() -> Dict[str, Any]:
    return {
        "account_id": 1,
        "max_universe": int(os.getenv("MAX_UNIVERSE", "1000")),
        "top_n": int(os.getenv("TOP_N", "10")),
        "exchange": "NASDAQ",
        "max_workers": 10,
        "min_final_score": float(os.getenv("MIN_FINAL_SCORE", "0.55")),
        "execute": False,
    }


def _write_report(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _write_github_outputs(
    path: Path | None,
    *,
    symbols: List[str],
    status: str,
    report_path: Path,
) -> None:
    if not path:
        return
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"backtest_symbols={','.join(symbols)}\n")
        stream.write(f"preselection_status={status}\n")
        stream.write(f"preselection_report={report_path}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Scanner discovery without Risk or Execution."
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/discover-analyze-trade",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        default=int(
            os.getenv("SCANNER_PRESELECTION_ATTEMPT_TIMEOUT_SECONDS", "900")
        ),
    )
    parser.add_argument(
        "--deadline",
        type=int,
        default=int(
            os.getenv("SCANNER_PRESELECTION_DEADLINE_SECONDS", "1200")
        ),
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(os.getenv("SCANNER_PRESELECTION_MAX_ATTEMPTS", "2")),
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=float(
            os.getenv("SCANNER_PRESELECTION_RETRY_DELAY_SECONDS", "5")
        ),
    )
    args = parser.parse_args()

    if args.attempt_timeout <= 0:
        parser.error("--attempt-timeout must be greater than zero")
    if args.deadline <= 0:
        parser.error("--deadline must be greater than zero")
    if args.max_attempts <= 0:
        parser.error("--max-attempts must be greater than zero")
    if args.retry_delay < 0:
        parser.error("--retry-delay must be zero or greater")

    payload = _payload_from_env()
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "scanner_preselection",
        "status": "running",
        "request": payload,
        "request_policy": {
            "url": args.url,
            "attempt_timeout_seconds": args.attempt_timeout,
            "deadline_seconds": args.deadline,
            "max_attempts": args.max_attempts,
            "retry_delay_seconds": args.retry_delay,
        },
        "response": None,
        "backtest_symbols": [],
    }

    try:
        response, attempts_used = _request_json(
            args.url,
            payload,
            attempt_timeout=args.attempt_timeout,
            deadline_seconds=args.deadline,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay,
        )
        symbols = extract_backtest_symbols(response)
    except Exception as exc:
        report["status"] = "error"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
        report["attempts_used"] = getattr(exc, "attempts_used", 0)
        report["request_errors"] = getattr(exc, "errors", [])
        _write_report(args.output, report)
        _write_github_outputs(
            args.github_output,
            symbols=[],
            status="error",
            report_path=args.output,
        )
        print(f"Scanner preselection failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    report.update(
        {
            "status": "success",
            "attempts_used": attempts_used,
            "response": response,
            "backtest_symbols": symbols,
        }
    )
    _write_report(args.output, report)
    _write_github_outputs(
        args.github_output,
        symbols=symbols,
        status="success",
        report_path=args.output,
    )
    print(
        "Scanner preselection complete: "
        f"attempts={attempts_used}, "
        f"symbols={','.join(symbols) if symbols else '<none>'}"
    )


if __name__ == "__main__":
    main()
