from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PAPER_API_URL = "https://paper-api.alpaca.markets"
SCHEMA_VERSION = "paper-profit-evidence.v1.1"


class ProfitEvidenceError(RuntimeError):
    pass


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _round(value: Decimal | None, places: str = "0.01") -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal(places)))


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProfitEvidenceError(f"Expected JSON object in {path.name}")
    return value


def _account_ref(account_id: Any) -> str:
    text = str(account_id or "").strip()
    if not text:
        return "unknown"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def fetch_alpaca_paper_account(
    *,
    api_url: str,
    api_key_id: str,
    secret_key: str,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    if api_url.strip().rstrip("/") != PAPER_API_URL:
        raise ProfitEvidenceError("Refusing to query a non-Paper Alpaca endpoint")
    if not api_key_id.strip() or not secret_key.strip():
        raise ProfitEvidenceError("Alpaca Paper credentials are required")

    request = urllib.request.Request(
        f"{PAPER_API_URL}/v2/account",
        headers={
            "Accept": "application/json",
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": secret_key,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProfitEvidenceError(
            f"Alpaca Paper account request returned HTTP {exc.code}"
        ) from exc
    except Exception as exc:
        raise ProfitEvidenceError(
            f"Alpaca Paper account request failed: {type(exc).__name__}"
        ) from exc

    if not isinstance(payload, dict) or not payload.get("id"):
        raise ProfitEvidenceError("Alpaca Paper account response is invalid")
    return payload


def _performance_evidence(position_review: dict[str, Any]) -> dict[str, Any]:
    performance = position_review.get("performance_session_risk")
    if not isinstance(performance, dict):
        performance = {}

    system_managed_realized_pnl = _decimal(
        performance.get("system_managed_realized_pnl")
    )
    provenance_verified = bool(performance.get("system_provenance_verified"))
    system_managed_trades_today = int(
        performance.get("system_managed_trades_today") or 0
    )

    # Current Performance_Agent session-risk data is account-level. It may be
    # derived from Database fills/trades that include broker-synchronized or
    # externally initiated activity. Therefore ordinary trades_today and
    # daily_realized_pnl are evidence of recorded account activity, but they are
    # not sufficient to prove AI-system provenance.
    if provenance_verified and (
        system_managed_trades_today <= 0 or system_managed_realized_pnl is None
    ):
        provenance_verified = False

    return {
        "daily_realized_pnl": _decimal(performance.get("daily_realized_pnl"))
        or Decimal("0"),
        "weekly_realized_pnl": _decimal(performance.get("weekly_realized_pnl"))
        or Decimal("0"),
        "trades_today": int(performance.get("trades_today") or 0),
        "consecutive_losses": int(performance.get("consecutive_losses") or 0),
        "warnings": list(performance.get("warnings") or []),
        "source": str(performance.get("source") or "unavailable"),
        "system_provenance_verified": provenance_verified,
        "system_managed_trades_today": system_managed_trades_today,
        "system_managed_realized_pnl": system_managed_realized_pnl,
        "provenance_source": str(
            performance.get("system_provenance_source") or "unavailable"
        ),
    }


def _attribution(
    *,
    day_change: Decimal,
    daily_realized_pnl: Decimal,
    trades_today: int,
    orders_submitted_this_cycle: bool,
    position_count: int,
    system_provenance_verified: bool,
    system_managed_trades_today: int,
    system_managed_realized_pnl: Decimal | None,
) -> dict[str, Any]:
    penny = Decimal("0.01")
    if abs(day_change) < penny and abs(daily_realized_pnl) < penny:
        return {
            "status": "flat",
            "confidence": "high",
            "reason_codes": ["broker_day_equity_flat", "no_realized_pnl_evidence"],
            "recorded_trade_pnl_consistent": True,
            "system_profit_proven": False,
            "provenance_verified": system_provenance_verified,
        }

    if (
        system_provenance_verified
        and system_managed_trades_today > 0
        and system_managed_realized_pnl is not None
    ):
        tolerance = max(Decimal("0.05"), abs(day_change) * Decimal("0.05"))
        if abs(day_change - system_managed_realized_pnl) <= tolerance:
            return {
                "status": "system_managed_realized_pnl_aligned",
                "confidence": "high",
                "reason_codes": [
                    "system_trade_provenance_verified",
                    "broker_day_change_matches_system_managed_realized_pnl",
                ],
                "recorded_trade_pnl_consistent": True,
                "system_profit_proven": day_change > 0,
                "provenance_verified": True,
            }
        return {
            "status": "system_managed_activity_partial_attribution",
            "confidence": "medium",
            "reason_codes": [
                "system_trade_provenance_verified",
                "broker_day_change_differs_from_system_managed_realized_pnl",
            ],
            "recorded_trade_pnl_consistent": False,
            "system_profit_proven": False,
            "provenance_verified": True,
        }

    if trades_today > 0 or abs(daily_realized_pnl) >= penny:
        tolerance = max(Decimal("0.05"), abs(day_change) * Decimal("0.05"))
        aligned = abs(day_change - daily_realized_pnl) <= tolerance
        if aligned:
            return {
                "status": "recorded_trade_pnl_aligned_provenance_unverified",
                "confidence": "medium",
                "reason_codes": [
                    "performance_agent_recorded_trade_activity_present",
                    "broker_day_change_matches_recorded_realized_pnl",
                    "system_trade_provenance_not_verified",
                ],
                "recorded_trade_pnl_consistent": True,
                "system_profit_proven": False,
                "provenance_verified": False,
            }
        return {
            "status": "recorded_trade_activity_partial_provenance_unverified",
            "confidence": "low",
            "reason_codes": [
                "performance_agent_recorded_trade_activity_present",
                "broker_day_change_differs_from_recorded_realized_pnl",
                "system_trade_provenance_not_verified",
            ],
            "recorded_trade_pnl_consistent": False,
            "system_profit_proven": False,
            "provenance_verified": False,
        }

    if orders_submitted_this_cycle:
        return {
            "status": "current_cycle_activity_attribution_pending",
            "confidence": "low",
            "reason_codes": [
                "broker_order_submitted_this_cycle",
                "no_proven_realized_system_fill_evidence_yet",
            ],
            "recorded_trade_pnl_consistent": False,
            "system_profit_proven": False,
            "provenance_verified": False,
        }

    if position_count > 0:
        return {
            "status": "mark_to_market_or_external_unproven",
            "confidence": "low",
            "reason_codes": [
                "open_positions_present",
                "no_proven_system_trade_evidence_for_day_change",
            ],
            "recorded_trade_pnl_consistent": False,
            "system_profit_proven": False,
            "provenance_verified": False,
        }

    return {
        "status": "unattributed_equity_change",
        "confidence": "high",
        "reason_codes": [
            "broker_equity_changed",
            "no_proven_system_trade_or_position_evidence",
        ],
        "recorded_trade_pnl_consistent": False,
        "system_profit_proven": False,
        "provenance_verified": False,
    }


def build_profit_evidence(
    *,
    account: dict[str, Any],
    hourly_report: dict[str, Any] | None = None,
    position_review: dict[str, Any] | None = None,
    baseline_equity: Decimal | None = None,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    hourly_report = hourly_report or {}
    position_review = position_review or {}

    equity = _decimal(account.get("equity"))
    last_equity = _decimal(account.get("last_equity"))
    if equity is None or equity <= 0:
        raise ProfitEvidenceError("Alpaca Paper equity is missing or invalid")
    if last_equity is None or last_equity <= 0:
        raise ProfitEvidenceError("Alpaca Paper last_equity is missing or invalid")

    day_change = equity - last_equity
    day_return = day_change / last_equity
    performance = _performance_evidence(position_review)
    positions = hourly_report.get("positions") or []
    open_orders = hourly_report.get("openOrders") or []
    position_count = len(positions) if isinstance(positions, list) else 0
    open_order_count = len(open_orders) if isinstance(open_orders, list) else 0
    orders_submitted = bool(hourly_report.get("broker_orders_submitted"))

    attribution = _attribution(
        day_change=day_change,
        daily_realized_pnl=performance["daily_realized_pnl"],
        trades_today=performance["trades_today"],
        orders_submitted_this_cycle=orders_submitted,
        position_count=position_count,
        system_provenance_verified=performance["system_provenance_verified"],
        system_managed_trades_today=performance["system_managed_trades_today"],
        system_managed_realized_pnl=performance["system_managed_realized_pnl"],
    )

    baseline: dict[str, Any] = {
        "configured": baseline_equity is not None and baseline_equity > 0,
        "attribution_status": "unproven_without_cash_flow_ledger",
    }
    if baseline_equity is not None and baseline_equity > 0:
        cumulative_change = equity - baseline_equity
        baseline.update(
            {
                "equity": _round(baseline_equity),
                "cumulative_equity_change": _round(cumulative_change),
                "cumulative_return_pct": _round(
                    cumulative_change / baseline_equity * Decimal("100"),
                    "0.0001",
                ),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_run_id": source_run_id,
        "account_ref": _account_ref(account.get("id")),
        "account_status": str(account.get("status") or "unknown"),
        "broker": {
            "equity": _round(equity),
            "last_equity": _round(last_equity),
            "cash": _round(_decimal(account.get("cash"))),
            "portfolio_value": _round(_decimal(account.get("portfolio_value"))),
            "buying_power": _round(_decimal(account.get("buying_power"))),
            "day_equity_change": _round(day_change),
            "day_return_pct": _round(day_return * Decimal("100"), "0.0001"),
        },
        "system_evidence": {
            "cycle_status": hourly_report.get("cycle_status"),
            "broker_orders_submitted_this_cycle": orders_submitted,
            "position_count": position_count,
            "open_order_count": open_order_count,
            "daily_realized_pnl": _round(performance["daily_realized_pnl"]),
            "weekly_realized_pnl": _round(performance["weekly_realized_pnl"]),
            "trades_today": performance["trades_today"],
            "consecutive_losses": performance["consecutive_losses"],
            "performance_source": performance["source"],
            "performance_warnings": performance["warnings"],
            "system_provenance_verified": performance[
                "system_provenance_verified"
            ],
            "system_managed_trades_today": performance[
                "system_managed_trades_today"
            ],
            "system_managed_realized_pnl": _round(
                performance["system_managed_realized_pnl"]
            ),
            "system_provenance_source": performance["provenance_source"],
        },
        "attribution": attribution,
        "baseline": baseline,
        "safety": {
            "paper_endpoint_only": True,
            "broker_mutation_performed": False,
            "credentials_emitted": False,
            "explicit_system_provenance_required_for_profit_claim": True,
        },
    }


def render_markdown(evidence: dict[str, Any]) -> str:
    broker = evidence["broker"]
    system = evidence["system_evidence"]
    attribution = evidence["attribution"]
    baseline = evidence["baseline"]
    lines = [
        "# Alpaca Paper Profit Evidence",
        "",
        f"- Equity: `${broker['equity']:,.2f}`",
        f"- Last equity: `${broker['last_equity']:,.2f}`",
        f"- Day equity change: `${broker['day_equity_change']:,.2f}` ({broker['day_return_pct']:.4f}%)",
        f"- Recorded daily realized P&L: `${system['daily_realized_pnl']:,.2f}`",
        f"- Recorded trades today: `{system['trades_today']}`",
        f"- System provenance verified: `{system['system_provenance_verified']}`",
        f"- Attribution: `{attribution['status']}` ({attribution['confidence']})",
        f"- System profit proven: `{attribution['system_profit_proven']}`",
    ]
    if baseline.get("configured"):
        lines.extend(
            [
                f"- Configured baseline equity: `${baseline['equity']:,.2f}`",
                f"- Cumulative equity change: `${baseline['cumulative_equity_change']:,.2f}` ({baseline['cumulative_return_pct']:.4f}%)",
                "- Baseline attribution remains unproven without a cash-flow ledger.",
            ]
        )
    lines.extend(
        [
            "",
            "A matching broker P&L and recorded trade P&L is not called AI-system profit unless explicit system-managed trade provenance is verified.",
            "",
            "This evidence is read-only and never places, cancels, or modifies broker orders.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture read-only Alpaca Paper P&L evidence"
    )
    parser.add_argument("--hourly-report", type=Path)
    parser.add_argument("--position-review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--source-run-id", default=os.getenv("SOURCE_RUN_ID"))
    args = parser.parse_args()

    account = fetch_alpaca_paper_account(
        api_url=os.getenv("ALPACA_API_URL", ""),
        api_key_id=os.getenv("ALPACA_API_KEY_ID", ""),
        secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
    )
    baseline = _decimal(os.getenv("PAPER_ACCOUNT_BASELINE_EQUITY"))
    evidence = build_profit_evidence(
        account=account,
        hourly_report=_read_json(args.hourly_report),
        position_review=_read_json(args.position_review),
        baseline_equity=baseline,
        source_run_id=args.source_run_id,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
    )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(evidence), encoding="utf-8")

    print(
        json.dumps(
            {
                "schema_version": evidence["schema_version"],
                "day_equity_change": evidence["broker"]["day_equity_change"],
                "attribution_status": evidence["attribution"]["status"],
                "system_profit_proven": evidence["attribution"][
                    "system_profit_proven"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
