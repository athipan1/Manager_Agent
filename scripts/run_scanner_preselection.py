from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

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


DEFAULT_NESTED_MINIMUM_BARS = 630
DEFAULT_FINAL_HOLDOUT_BARS = 252
DEFAULT_BACKTEST_HISTORY_DAYS = 5 * 365


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


def _positive_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _required_backtest_history_bars() -> int:
    """Mirror the nested promotion history contract without weakening it.

    Backtest_Agent requires BACKTEST_NESTED_MINIMUM_BARS research bars plus the
    sealed final holdout. An explicit aggregate override is supported for future
    contract versions, but it may never resolve to a non-positive value.
    """

    explicit = os.getenv("BACKTEST_HISTORY_REQUIRED_BARS")
    if explicit not in (None, ""):
        try:
            value = int(str(explicit).strip())
        except ValueError as exc:
            raise ValueError("BACKTEST_HISTORY_REQUIRED_BARS must be an integer") from exc
        if value <= 0:
            raise ValueError("BACKTEST_HISTORY_REQUIRED_BARS must be greater than zero")
        return value

    research_bars = _positive_int_env(
        "BACKTEST_NESTED_MINIMUM_BARS",
        DEFAULT_NESTED_MINIMUM_BARS,
    )
    if not _bool_env("BACKTEST_FINAL_HOLDOUT_ENABLED", True):
        # Production nested promotion itself will reject this configuration. Do
        # not pretend a shorter history window is production compatible here.
        raise ValueError(
            "BACKTEST_FINAL_HOLDOUT_ENABLED must remain true for nested promotion"
        )
    holdout_bars = _positive_int_env(
        "BACKTEST_FINAL_HOLDOUT_BARS",
        DEFAULT_FINAL_HOLDOUT_BARS,
    )
    return research_bars + holdout_bars


def _alpaca_timeframe(value: str) -> str | None:
    normalized = str(value or "1d").strip().lower()
    return {
        "1d": "1Day",
        "1day": "1Day",
        "day": "1Day",
        "1h": "1Hour",
        "1hour": "1Hour",
        "60m": "1Hour",
        "30m": "30Min",
        "15m": "15Min",
        "5m": "5Min",
        "1m": "1Min",
    }.get(normalized)


def _backtest_date_range() -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(
        days=_positive_int_env("BACKTEST_HISTORY_DAYS", DEFAULT_BACKTEST_HISTORY_DAYS)
    )
    return (
        os.getenv("BACKTEST_START") or start.isoformat(),
        os.getenv("BACKTEST_END") or end.isoformat(),
    )


def _fetch_alpaca_bar_count(symbol: str, required_bars: int) -> int | None:
    """Return Alpaca bar count, or None when precheck evidence is unavailable.

    Unknown evidence does not authorize a candidate. It simply preserves the
    existing fail-closed Backtest decision so a transient data-provider problem
    cannot create a false rejection or a false production approval.
    """

    api_key = str(os.getenv("ALPACA_API_KEY_ID") or "").strip()
    secret = str(os.getenv("ALPACA_SECRET_KEY") or "").strip()
    if not api_key or not secret:
        return None

    timeframe = _alpaca_timeframe(os.getenv("BACKTEST_TIMEFRAME", "1d"))
    if timeframe is None:
        return None

    start, end = _backtest_date_range()
    base_url = str(
        os.getenv("ALPACA_DATA_API_URL") or "https://data.alpaca.markets"
    ).rstrip("/")
    feed = str(os.getenv("ALPACA_DATA_FEED") or "iex").strip()
    total = 0
    page_token: str | None = None
    max_pages = 20

    for _ in range(max_pages):
        query = {
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "limit": "10000",
            "adjustment": "raw",
            "feed": feed,
            "sort": "asc",
        }
        if page_token:
            query["page_token"] = page_token
        url = (
            f"{base_url}/v2/stocks/{urllib.parse.quote(symbol, safe='')}/bars?"
            + urllib.parse.urlencode(query)
        )
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=float(os.getenv("BACKTEST_HISTORY_PRECHECK_TIMEOUT_SECONDS", "20")),
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (
            TimeoutError,
            socket.timeout,
            urllib.error.HTTPError,
            urllib.error.URLError,
            ConnectionResetError,
            json.JSONDecodeError,
        ):
            return None

        bars = payload.get("bars") if isinstance(payload, dict) else None
        if not isinstance(bars, list):
            return None
        total += len(bars)
        if total >= required_bars:
            return total
        page_token = str(payload.get("next_page_token") or "").strip() or None
        if not page_token:
            return total

    return total


def _symbol_from_row(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("symbol") or row.get("ticker") or "").strip().upper()


def _history_gate_research_selection(
    data: Dict[str, Any],
    *,
    fetch_bar_count: Callable[[str, int], int | None] | None = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Re-run the existing research selector after known history failures.

    This preserves all bucket, score, evidence, verdict and fail-closed rules.
    Only candidates proven to have fewer bars than Backtest_Agent requires are
    removed, allowing the same selector to backfill from the next ranked row.
    """

    ranked_rows = data.get("ranked_candidates") or []
    if not isinstance(ranked_rows, list) or not ranked_rows:
        return {}, {
            "status": "not_applicable",
            "reason": "ranked_candidates_unavailable",
            "required_bars": _required_backtest_history_bars(),
            "evaluations": [],
            "rejected_symbols": [],
            "unknown_symbols": [],
        }

    threshold = _research_backtest_threshold(data)
    baseline = select_research_backtest_candidates(
        ranked_rows,
        min_final_score=threshold,
    )
    eligible_symbols = [
        str(row.get("symbol") or "").strip().upper()
        for row in baseline.get("evaluations") or []
        if isinstance(row, dict)
        and row.get("eligible") is True
        and str(row.get("symbol") or "").strip()
    ]
    eligible_symbols = list(dict.fromkeys(eligible_symbols))
    required_bars = _required_backtest_history_bars()
    fetcher = fetch_bar_count or _fetch_alpaca_bar_count
    evaluations: List[Dict[str, Any]] = []
    rejected_symbols: List[str] = []
    unknown_symbols: List[str] = []
    evidence_by_symbol: Dict[str, Dict[str, Any]] = {}

    for symbol in eligible_symbols:
        observed = fetcher(symbol, required_bars)
        if observed is None:
            evidence = {
                "symbol": symbol,
                "status": "unknown",
                "bars_observed": None,
                "bars_required": required_bars,
                "history_eligible": None,
                "decision": "defer_to_exact_backtest",
            }
            unknown_symbols.append(symbol)
        elif observed < required_bars:
            evidence = {
                "symbol": symbol,
                "status": "insufficient_history",
                "bars_observed": int(observed),
                "bars_required": required_bars,
                "history_eligible": False,
                "decision": "exclude_and_backfill",
            }
            rejected_symbols.append(symbol)
        else:
            evidence = {
                "symbol": symbol,
                "status": "passed",
                "bars_observed": int(observed),
                "bars_required": required_bars,
                "history_eligible": True,
                "decision": "eligible_for_exact_backtest",
            }
        evidence_by_symbol[symbol] = evidence
        evaluations.append(evidence)

    blocked = set(rejected_symbols)
    filtered_rows = [
        row
        for row in ranked_rows
        if _symbol_from_row(row) not in blocked
    ]
    selection = select_research_backtest_candidates(
        filtered_rows,
        min_final_score=threshold,
    )
    for item in selection.get("selected") or []:
        if not isinstance(item, dict):
            continue
        symbol = _symbol_from_row(item)
        evidence = evidence_by_symbol.get(symbol)
        if evidence:
            item["pre_backtest_history_eligible"] = evidence["history_eligible"]
            item["history_bars_observed"] = evidence["bars_observed"]
            item["history_bars_required"] = evidence["bars_required"]
            item["history_precheck_status"] = evidence["status"]

    gate = {
        "schema_version": "pre-backtest-history-gate.v1",
        "status": "completed",
        "required_bars": required_bars,
        "research_minimum_bars": _positive_int_env(
            "BACKTEST_NESTED_MINIMUM_BARS", DEFAULT_NESTED_MINIMUM_BARS
        ),
        "sealed_holdout_bars": _positive_int_env(
            "BACKTEST_FINAL_HOLDOUT_BARS", DEFAULT_FINAL_HOLDOUT_BARS
        ),
        "timeframe": os.getenv("BACKTEST_TIMEFRAME", "1d"),
        "eligible_research_symbols_checked": len(eligible_symbols),
        "rejected_symbols": rejected_symbols,
        "unknown_symbols": unknown_symbols,
        "backfilled_selection_count": len(selection.get("selected") or []),
        "evaluations": evaluations,
        "safety": {
            "production_authority_granted": False,
            "risk_execution_authority_granted": False,
            "unknown_history_deferred_to_exact_backtest": True,
            "backtest_thresholds_relaxed": False,
        },
    }
    selection["pre_backtest_history_gate"] = gate
    return selection, gate


def extract_backtest_symbols(response: Dict[str, Any]) -> List[str]:
    """Extract broker-isolated exact Backtest symbols from Manager discovery.

    Ranked candidates use a research-only eligibility policy. HOLD may reach
    Backtest when classification/evidence/score gates pass, while SELL,
    STRONG_SELL and Scanner fail-closed rows remain blocked. Candidates proven
    to lack the nested promotion history contract are removed before exact
    Backtest and the same research selector backfills from the next ranked row.
    This never grants Risk or Execution authority. Older responses without ranked
    rows keep the legacy production-selected-position fallback.
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
        research_selection, history_gate = _history_gate_research_selection(data)
        data["research_backtest_selection"] = research_selection
        data["pre_backtest_history_gate"] = history_gate
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

    response_data = response.get("data") if isinstance(response, dict) else None
    history_gate = (
        response_data.get("pre_backtest_history_gate")
        if isinstance(response_data, dict)
        else None
    )
    report.update(
        {
            "status": "success",
            "outcome": "NO_TRADE" if not symbols else "CANDIDATES",
            "controlled_no_trade": controlled_no_trade,
            "attempts_used": attempts_used,
            "response": response,
            "backtest_symbols": symbols,
            "pre_backtest_history_gate": history_gate,
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
    rejected = []
    if isinstance(history_gate, dict):
        rejected = history_gate.get("rejected_symbols") or []
    print(
        "Scanner preselection complete: "
        f"attempts={attempts_used}, "
        f"outcome={report['outcome']}, "
        f"symbols={','.join(symbols) if symbols else '<none>'}, "
        f"history_rejected={','.join(rejected) if rejected else '<none>'}"
    )


if __name__ == "__main__":
    main()
