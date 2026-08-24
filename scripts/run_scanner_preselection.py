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

try:
    from scripts.run_profitability_funnel_audit import run_audit
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from run_profitability_funnel_audit import run_audit

try:
    from app.services.research_backtest_selection_service import (
        select_research_backtest_candidates,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services.research_backtest_selection_service import (
        select_research_backtest_candidates,
    )


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


def _is_controlled_no_trade_response(response: Dict[str, Any]) -> bool:
    """Return True only when Scanner explicitly produced a safe NO_TRADE result."""

    data = response.get("data")
    if not isinstance(data, dict):
        return False
    scanner_data = data.get("scanner_data")
    if not isinstance(scanner_data, dict):
        return False
    metadata = scanner_data.get("metadata")
    if not isinstance(metadata, dict):
        return False
    gate = metadata.get("scanner_opportunity_gate")
    if not isinstance(gate, dict):
        return False

    try:
        workflow_failures = int(gate.get("workflow_failure_count", 0))
        controlled_no_trade = int(gate.get("controlled_no_trade_count", 0))
        passed = int(gate.get("passed_count", 0))
    except (TypeError, ValueError):
        return False

    return workflow_failures == 0 and controlled_no_trade > 0 and passed == 0


def _research_backtest_threshold(data: Dict[str, Any]) -> float:
    bucket_selection = data.get("bucket_selection")
    if isinstance(bucket_selection, dict):
        summary = bucket_selection.get("summary")
        if isinstance(summary, dict):
            raw_value = summary.get("min_final_score")
            try:
                if raw_value not in (None, ""):
                    return float(raw_value)
            except (TypeError, ValueError):
                pass
    return float(os.getenv("MIN_FINAL_SCORE", "0.55"))


def extract_backtest_symbols(response: Dict[str, Any]) -> List[str]:
    """Extract broker-isolated exact Backtest symbols from Manager discovery.

    Ranked candidates use a research-only eligibility policy. HOLD may reach
    Backtest when classification/evidence/score gates pass, while SELL,
    STRONG_SELL and Scanner fail-closed rows remain blocked. This does not grant
    Risk or Execution authority. Older responses without ranked rows keep the
    legacy production-selected-position fallback.
    """

    if response.get("status") != "success":
        if _is_controlled_no_trade_response(response):
            return []
        raise ValueError(f"Scanner preselection failed: {response}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise ValueError("Scanner preselection response has no data object")

    ranked_rows = data.get("ranked_candidates") or []
    if isinstance(ranked_rows, list) and ranked_rows:
        research_selection = select_research_backtest_candidates(
            ranked_rows,
            min_final_score=_research_backtest_threshold(data),
        )
        data["research_backtest_selection"] = research_selection
        positions = research_selection.get("selected") or []
    else:
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
        "portfolio_cycle_id": os.getenv("PORTFOLIO_CYCLE_ID") or None,
    }


def _write_report(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _funnel_paths(report_path: Path) -> tuple[Path, Path]:
    return (
        report_path.parent / "hourly-profitability-funnel.json",
        report_path.parent / "hourly-profitability-funnel.md",
    )


def _write_profitability_funnel(report_path: Path) -> None:
    """Emit diagnostic funnel artifacts without gaining trading authority."""

    output_path, markdown_path = _funnel_paths(report_path)
    try:
        run_audit(
            discovery_path=report_path,
            upstream_report_path=None,
            output_path=output_path,
            markdown_path=markdown_path,
            source_run_id=os.getenv("GITHUB_RUN_ID") or None,
            source_run_conclusion=None,
        )
    except Exception as exc:  # pragma: no cover - last-resort diagnostic isolation
        print(
            f"Profitability funnel diagnostic failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
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
    funnel_path, _ = _funnel_paths(report_path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"backtest_symbols={','.join(symbols)}\n")
        stream.write(f"preselection_status={status}\n")
        stream.write(f"preselection_report={report_path}\n")
        stream.write(f"profitability_funnel_report={funnel_path}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Scanner discovery without Risk or Execution."
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/scanner-preselection",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        default=int(os.getenv("SCANNER_PRESELECTION_ATTEMPT_TIMEOUT_SECONDS", "900")),
    )
    parser.add_argument(
        "--deadline",
        type=int,
        default=int(os.getenv("SCANNER_PRESELECTION_DEADLINE_SECONDS", "1200")),
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(os.getenv("SCANNER_PRESELECTION_MAX_ATTEMPTS", "2")),
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=float(os.getenv("SCANNER_PRESELECTION_RETRY_DELAY_SECONDS", "5")),
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
        controlled_no_trade = _is_controlled_no_trade_response(response)
        symbols = extract_backtest_symbols(response)
    except Exception as exc:
        report["status"] = "error"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
        report["attempts_used"] = getattr(exc, "attempts_used", 0)
        report["request_errors"] = getattr(exc, "errors", [])
        _write_report(args.output, report)
        _write_profitability_funnel(args.output)
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
            "outcome": "NO_TRADE" if not symbols else "CANDIDATES",
            "controlled_no_trade": controlled_no_trade,
            "attempts_used": attempts_used,
            "response": response,
            "backtest_symbols": symbols,
        }
    )
    _write_report(args.output, report)
    _write_profitability_funnel(args.output)
    _write_github_outputs(
        args.github_output,
        symbols=symbols,
        status="success",
        report_path=args.output,
    )
    print(
        "Scanner preselection complete: "
        f"attempts={attempts_used}, "
        f"outcome={report['outcome']}, "
        f"symbols={','.join(symbols) if symbols else '<none>'}"
    )


if __name__ == "__main__":
    main()
