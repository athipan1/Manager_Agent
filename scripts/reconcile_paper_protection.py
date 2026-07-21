from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hourly_runtime_loader import runtime

is_placeholder_secret = runtime.is_placeholder_secret

EXECUTION_CONFIRMATION_PHRASE = "EXECUTE_PAPER_PROTECTION_RECONCILIATION"
ATTENTION_STATUSES = {"partially_protected", "unprotected", "stop_only"}
FULLY_PROTECTED_STATUSES = {"bracket_protected", "tp_sl_protected"}

EXECUTION_URL = os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006").rstrip("/")
RISK_URL = os.getenv("RISK_AGENT_URL", "http://localhost:8007").rstrip("/")
EXECUTION_API_KEY = os.getenv("EXECUTION_API_KEY", "").strip()
CORRELATION_ID = os.getenv("PORTFOLIO_CYCLE_ID", "paper-protection-reconciliation").strip()
EXECUTE_PAPER = os.getenv("EXECUTE_PAPER_PROTECTION_RECONCILIATION", "false").strip().lower() == "true"
REWARD_RISK_RATIO = float(os.getenv("PROTECTION_REWARD_RISK_RATIO", "2.0"))
REPORT_PATH = Path(os.getenv("PROTECTION_REPORT_PATH", "reports/paper-protection-reconciliation.json"))


def request_json(
    base_url: str,
    path: str,
    *,
    payload: Dict[str, Any] | None = None,
    method: str = "GET",
    api_key: str | None = None,
    timeout: int = 120,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    body = None
    headers: Dict[str, str] = {"X-Correlation-ID": CORRELATION_ID}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["X-API-KEY"] = api_key
    last_error = "request failed"
    for attempt in range(1, max(1, max_attempts) + 1):
        request = urllib.request.Request(
            f"{base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code < 500:
                break
        except Exception as exc:
            last_error = type(exc).__name__
        if attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 2))
    raise RuntimeError(
        f"{method} {path} failed after bounded retries: {last_error}"
    )


def unwrap(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get("data")
    return data if isinstance(data, dict) else value


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_stop_price(row: Dict[str, Any]) -> float | None:
    for order in row.get("protective_orders") or []:
        if not isinstance(order, dict):
            continue
        price = _float(
            order.get("stop_price")
            or order.get("trigger_price")
            or order.get("price")
        )
        if price is not None:
            return price
    return None


def _attention_rows(diagnostics: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        dict(row)
        for row in diagnostics.get("positions") or []
        if isinstance(row, dict)
        and str(row.get("protection_status") or "").lower()
        in ATTENTION_STATUSES
    ]


def _protection_summary(diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    rows = [row for row in diagnostics.get("positions") or [] if isinstance(row, dict)]
    return {
        "position_count": len(rows),
        "fully_protected": sorted(
            str(row.get("symbol") or "")
            for row in rows
            if str(row.get("protection_status") or "").lower()
            in FULLY_PROTECTED_STATUSES
        ),
        "needs_attention": [
            {
                "symbol": row.get("symbol"),
                "status": row.get("protection_status"),
                "position_qty": row.get("position_qty"),
                "stop_covered_qty": row.get("stop_covered_qty"),
                "take_profit_covered_qty": row.get("take_profit_covered_qty"),
            }
            for row in _attention_rows(diagnostics)
        ],
    }


def build_risk_proposals(rows: Iterable[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    proposals: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        quantity = _float(row.get("position_qty"))
        current_price = _float(row.get("current_price"))
        entry_price = _float(row.get("avg_entry_price")) or current_price
        if not symbol or quantity is None or current_price is None or entry_price is None:
            failures.append(
                {
                    "symbol": symbol or row.get("symbol"),
                    "reason": "missing_symbol_quantity_or_reference_price",
                    "diagnostic": row,
                }
            )
            continue

        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": "long",
            "quantity": quantity,
            "entry_price": entry_price,
            "current_price": current_price,
            "strategy_bucket": "unassigned",
            "reward_risk_ratio": REWARD_RISK_RATIO,
        }
        existing_stop = _first_stop_price(row)
        if existing_stop is not None and existing_stop < current_price:
            payload["existing_stop_price"] = existing_stop

        try:
            response = request_json(
                RISK_URL,
                "/risk/protection-plan",
                payload=payload,
                method="POST",
            )
            proposal = unwrap(response)
            if proposal.get("status") != "approved":
                raise RuntimeError(
                    f"Risk proposal not approved: {json.dumps(response, default=str)}"
                )
            proposals.append(proposal)
        except Exception as exc:
            failures.append(
                {
                    "symbol": symbol,
                    "reason": str(exc),
                    "request": payload,
                }
            )
    return proposals, failures


def fetch_diagnostics() -> Dict[str, Any]:
    return unwrap(
        request_json(
            EXECUTION_URL,
            "/broker/protection-diagnostics",
            api_key=EXECUTION_API_KEY,
        )
    )


def wait_for_verified_protection(attempts: int = 8, delay_seconds: int = 5) -> Dict[str, Any]:
    latest: Dict[str, Any] = {}
    for _ in range(attempts):
        latest = fetch_diagnostics()
        if not _attention_rows(latest):
            return latest
        time.sleep(delay_seconds)
    return latest


def write_report(report: Dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    markdown_path = REPORT_PATH.with_suffix(".md")
    before = report.get("before_summary") or {}
    after = report.get("after_summary") or {}
    lines = [
        "# Paper Protection Reconciliation",
        "",
        f"Generated at UTC: `{report.get('generated_at')}`",
        f"Execution enabled: `{report.get('execute_paper')}`",
        f"Status: `{report.get('status')}`",
        "",
        "## Before",
        f"- Fully protected: `{', '.join(before.get('fully_protected') or []) or '-'}`",
        f"- Needs attention: `{len(before.get('needs_attention') or [])}`",
        "",
        "## Risk Proposals",
        f"- Approved proposals: `{len(report.get('risk_proposals') or [])}`",
        f"- Proposal failures: `{len(report.get('proposal_failures') or [])}`",
        "",
        "## Execution",
        "```json",
        json.dumps(report.get("execution") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## After",
        f"- Fully protected: `{', '.join(after.get('fully_protected') or []) or '-'}`",
        f"- Needs attention: `{len(after.get('needs_attention') or [])}`",
        "",
    ]
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if EXECUTE_PAPER and is_placeholder_secret(EXECUTION_API_KEY):
        print(
            "Paper protection reconciliation refused a missing or placeholder Execution key.",
            file=sys.stderr,
        )
        return 1
    before = fetch_diagnostics()
    attention = _attention_rows(before)
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execute_paper": EXECUTE_PAPER,
        "before": before,
        "before_summary": _protection_summary(before),
        "risk_proposals": [],
        "proposal_failures": [],
        "preview": None,
        "execution": None,
        "after": before,
        "after_summary": _protection_summary(before),
    }

    if not attention:
        report["status"] = "already_fully_protected"
        write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0

    proposals, failures = build_risk_proposals(attention)
    report["risk_proposals"] = proposals
    report["proposal_failures"] = failures
    if failures or len(proposals) != len(attention):
        report["status"] = "blocked_risk_proposal_failure"
        write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 2

    preview_response = request_json(
        EXECUTION_URL,
        "/broker/protection-reconciliation/preview",
        payload={"risk_proposals": proposals},
        method="POST",
        api_key=EXECUTION_API_KEY,
    )
    preview = unwrap(preview_response)
    report["preview"] = preview_response
    ticket = preview.get("ticket") or {}
    ready_symbols = list(ticket.get("symbols") or [])

    if not ready_symbols:
        report["status"] = "blocked_no_ready_reconciliation_plans"
        write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 3

    if not EXECUTE_PAPER:
        report["status"] = "preview_ready_execution_disabled"
        write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0

    execution_payload = {
        "risk_proposals": proposals,
        "reconciliation_ticket_id": ticket.get("ticket_id"),
        "execution_confirmation_phrase": EXECUTION_CONFIRMATION_PHRASE,
        "execute_paper": True,
        "symbols": ready_symbols,
        "allow_multi_symbol": True,
    }
    execution_response = request_json(
        EXECUTION_URL,
        "/broker/protection-reconciliation/execute",
        payload=execution_payload,
        method="POST",
        api_key=EXECUTION_API_KEY,
        timeout=240,
    )
    execution = unwrap(execution_response)
    report["execution"] = execution_response

    after = wait_for_verified_protection()
    report["after"] = after
    report["after_summary"] = _protection_summary(after)
    remaining = _attention_rows(after)
    critical_gap = bool(execution.get("critical_protection_gap"))
    if critical_gap or remaining:
        report["status"] = "reconciliation_incomplete"
        write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 4

    report["status"] = "reconciled_and_verified"
    write_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
