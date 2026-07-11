from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ATTENTION_STATUSES = {"partially_protected", "unprotected", "stop_only"}
PENDING_CANCEL_STATUS = "pending_cancel"

EXECUTION_URL = os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006").rstrip("/")
EXECUTION_API_KEY = os.getenv("EXECUTION_API_KEY", "dev_execution_key").strip()
ALPACA_API_URL = os.getenv("ALPACA_API_URL", "https://paper-api.alpaca.markets").strip()
ALPACA_API_KEY_ID = os.getenv("ALPACA_API_KEY_ID", "").strip()
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "").strip()
REPORT_PATH = Path(
    os.getenv(
        "PROTECTION_REPORT_PATH",
        "reports/paper-protection-reconciliation.json",
    )
)


def _normalize_alpaca_base_url(value: str) -> str:
    base = (value or "https://paper-api.alpaca.markets").rstrip("/")
    if base.endswith("/v2"):
        base = base[:-3]
    return base


def request_json(
    url: str,
    *,
    headers: Dict[str, str] | None = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed with HTTP {exc.code}: {raw}") from exc
    except Exception as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc


def unwrap(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get("data")
    return data if isinstance(data, dict) else value


def fetch_diagnostics() -> Dict[str, Any]:
    response = request_json(
        f"{EXECUTION_URL}/broker/protection-diagnostics",
        headers={"X-API-KEY": EXECUTION_API_KEY},
        timeout=60,
    )
    return unwrap(response)


def fetch_market_clock() -> Dict[str, Any]:
    if not ALPACA_API_KEY_ID or not ALPACA_SECRET_KEY:
        raise RuntimeError("Alpaca credentials are required for the market clock gate")
    base = _normalize_alpaca_base_url(ALPACA_API_URL)
    return request_json(
        f"{base}/v2/clock",
        headers={
            "APCA-API-KEY-ID": ALPACA_API_KEY_ID,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        },
        timeout=30,
    )


def _status(value: Any) -> str:
    return str(value or "").strip().lower()


def attention_symbols(diagnostics: Dict[str, Any]) -> set[str]:
    return {
        str(row.get("symbol") or "").strip().upper()
        for row in diagnostics.get("positions") or []
        if isinstance(row, dict)
        and _status(row.get("protection_status")) in ATTENTION_STATUSES
        and str(row.get("symbol") or "").strip()
    }


def pending_cancel_orders(diagnostics: Dict[str, Any]) -> List[Dict[str, Any]]:
    pending: Dict[str, Dict[str, Any]] = {}
    for row in diagnostics.get("positions") or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        for order in row.get("open_orders") or []:
            if not isinstance(order, dict):
                continue
            if _status(order.get("status")) != PENDING_CANCEL_STATUS:
                continue
            order_id = str(
                order.get("id")
                or order.get("broker_order_id")
                or order.get("order_id")
                or ""
            ).strip()
            key = order_id or f"{symbol}:{len(pending)}"
            pending[key] = {
                "symbol": symbol,
                "broker_order_id": order_id or None,
                "status": PENDING_CANCEL_STATUS,
                "qty": order.get("qty") or order.get("quantity"),
                "order_class": order.get("order_class"),
                "type": order.get("type") or order.get("order_type"),
                "submitted_at": order.get("submitted_at"),
                "created_at": order.get("created_at"),
            }
    return sorted(
        pending.values(),
        key=lambda item: (str(item.get("symbol") or ""), str(item.get("broker_order_id") or "")),
    )


def should_defer_for_closed_market(
    diagnostics: Dict[str, Any],
    market_clock: Dict[str, Any],
) -> bool:
    pending = pending_cancel_orders(diagnostics)
    if not pending or market_clock.get("is_open") is not False:
        return False
    pending_symbols = {
        str(item.get("symbol") or "").strip().upper()
        for item in pending
        if str(item.get("symbol") or "").strip()
    }
    needs_attention = attention_symbols(diagnostics)
    return bool(needs_attention) and needs_attention.issubset(pending_symbols)


def protection_summary(diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    rows = [row for row in diagnostics.get("positions") or [] if isinstance(row, dict)]
    return {
        "position_count": len(rows),
        "fully_protected": sorted(
            str(row.get("symbol") or "")
            for row in rows
            if _status(row.get("protection_status"))
            in {"bracket_protected", "tp_sl_protected"}
        ),
        "needs_attention": sorted(attention_symbols(diagnostics)),
    }


def set_github_output(name: str, value: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def write_deferred_report(
    diagnostics: Dict[str, Any],
    market_clock: Dict[str, Any],
    pending_orders: List[Dict[str, Any]],
) -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "deferred_pending_cancel_market_closed",
        "safety": "no_broker_mutation_while_pending_cancel_and_market_closed",
        "market_clock": market_clock,
        "before": diagnostics,
        "before_summary": protection_summary(diagnostics),
        "pending_cancel_orders": pending_orders,
        "deferred_symbols": sorted(
            {
                str(item.get("symbol") or "").strip().upper()
                for item in pending_orders
                if str(item.get("symbol") or "").strip()
            }
        ),
        "retry_policy": (
            "Retry automatically after the next successful Hourly Auto Trading run. "
            "Mutation remains blocked until Alpaca reports the market open or the "
            "pending cancellations reach a terminal canceled state."
        ),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    markdown_path = REPORT_PATH.with_suffix(".md")
    symbols = ", ".join(report["deferred_symbols"]) or "-"
    markdown_path.write_text(
        "\n".join(
            [
                "# Paper Protection Reconciliation",
                "",
                f"Generated at UTC: `{report['generated_at']}`",
                f"Status: `{report['status']}`",
                f"Market open: `{market_clock.get('is_open')}`",
                f"Next open: `{market_clock.get('next_open')}`",
                f"Deferred symbols: `{symbols}`",
                "",
                "The broker still reports legacy orders as `pending_cancel`. No new "
                "replacement order was submitted while those orders continued to reserve quantity.",
                "",
                f"Retry policy: {report['retry_policy']}",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    diagnostics = fetch_diagnostics()
    pending_orders = pending_cancel_orders(diagnostics)
    if not pending_orders:
        set_github_output("deferred", "false")
        print("No pending_cancel orders detected; reconciliation may proceed.")
        return 0

    try:
        market_clock = fetch_market_clock()
    except Exception as exc:
        set_github_output("deferred", "false")
        print(f"::error::Unable to determine Alpaca market state: {exc}")
        return 2

    if should_defer_for_closed_market(diagnostics, market_clock):
        write_deferred_report(diagnostics, market_clock, pending_orders)
        set_github_output("deferred", "true")
        symbols = ", ".join(
            sorted({str(item.get('symbol') or '') for item in pending_orders})
        )
        print(
            "::warning::Paper protection reconciliation deferred because Alpaca "
            f"market is closed and legacy orders remain pending_cancel: {symbols}. "
            f"Next open: {market_clock.get('next_open')}"
        )
        return 0

    set_github_output("deferred", "false")
    print(
        "Pending cancellations detected, but the market is open or other unprotected "
        "positions require immediate handling; reconciliation will proceed fail-closed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
