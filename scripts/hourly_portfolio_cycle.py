#!/usr/bin/env python3
"""Fail-closed hourly portfolio review and Manager execution coordinator."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hourly_runtime_loader import runtime

JsonHttpClient = runtime.JsonHttpClient
RuntimeSafetyError = runtime.RuntimeSafetyError


SAFE_SYNC_STATUSES = {"synced", "in_sync", "ok", "matched"}
SAFE_PROTECTION_STATUSES = {"bracket_protected", "tp_sl_protected"}
MANUAL_EXIT_ACTIONS = {"partial_exit", "exit_all"}


def unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def broker_sync_status(value: Any) -> str:
    data = as_dict(unwrap(value))
    mismatch = as_dict(data.get("mismatch"))
    summary = as_dict(mismatch.get("summary"))
    return str(summary.get("status") or data.get("status") or "").lower()


def require_safe_broker_sync(value: Any, *, stage: str) -> dict[str, Any]:
    data = as_dict(unwrap(value))
    status = broker_sync_status(value)
    execution_push = as_dict(data.get("database_sync"))
    execution_reconcile_ok = (
        data.get("ok") is True
        and execution_push.get("status") == "success"
    )
    database_status_ok = status in SAFE_SYNC_STATUSES
    if not execution_reconcile_ok and not database_status_ok:
        raise RuntimeSafetyError(
            f"{stage} broker reconciliation did not prove Database/Alpaca parity."
        )
    return data


def protection_gaps(value: Any) -> list[dict[str, Any]]:
    diagnostics = as_dict(unwrap(value))
    return [
        row
        for row in as_list(diagnostics.get("positions"))
        if str(row.get("protection_status") or "").lower()
        not in SAFE_PROTECTION_STATUSES
        or number(row.get("unprotected_quantity")) > 0
        or bool(row.get("duplicate_protection"))
        or bool(row.get("quantity_mismatch"))
    ]


def classify_position_action(
    *,
    position: dict[str, Any],
    protection: dict[str, Any],
    portfolio_position: dict[str, Any],
    profit_plan: dict[str, Any],
) -> str:
    protection_status = str(protection.get("protection_status") or "").lower()
    if protection_status not in SAFE_PROTECTION_STATUSES:
        return "REPLACE_PROTECTION"
    portfolio_action = str(portfolio_position.get("action") or "").lower()
    primary = str(profit_plan.get("primary_action") or "hold").lower()
    if primary == "exit_all":
        return "EXIT_ALL_RECOMMENDATION"
    if primary == "partial_exit" or portfolio_action == "reduce":
        return "PARTIAL_EXIT_RECOMMENDATION"
    if primary == "move_stop":
        return "MOVE_STOP"
    if portfolio_action == "increase":
        return "ADD_POSITION"
    if not str(position.get("symbol") or "").strip():
        return "BLOCKED"
    return "HOLD"


class CycleClients:
    def __init__(self, correlation_id: str) -> None:
        self.correlation_id = correlation_id
        execution_key = os.getenv("EXECUTION_API_KEY", "")
        database_key = os.getenv("DATABASE_AGENT_API_KEY", "")
        portfolio_key = os.getenv("PORTFOLIO_AGENT_API_KEY", "")
        self.execution = JsonHttpClient(
            os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006"),
            "Execution_Agent",
            {"X-API-KEY": execution_key} if execution_key else {},
            timeout_seconds=30,
        )
        self.database = JsonHttpClient(
            os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"),
            "Railway Database_Agent",
            {"X-API-KEY": database_key} if database_key else {},
            timeout_seconds=30,
        )
        self.manager = JsonHttpClient(
            os.getenv("MANAGER_AGENT_URL", "http://localhost:8001"),
            "Manager_Agent",
            timeout_seconds=300,
        )
        self.technical = JsonHttpClient(
            os.getenv("TECHNICAL_AGENT_URL", "http://localhost:8002"),
            "Technical_Agent",
            timeout_seconds=90,
        )
        self.fundamental = JsonHttpClient(
            os.getenv("FUNDAMENTAL_AGENT_URL", "http://localhost:8003"),
            "Fundamental_Agent",
            timeout_seconds=90,
        )
        self.market = JsonHttpClient(
            os.getenv("MARKET_REGIME_AGENT_URL", "http://localhost:8013"),
            "Market_Regime_Agent",
            timeout_seconds=30,
        )
        self.portfolio = JsonHttpClient(
            os.getenv("PORTFOLIO_AGENT_URL", "http://localhost:8009"),
            "Portfolio_Agent",
            {"X-API-KEY": portfolio_key} if portfolio_key else {},
            timeout_seconds=30,
        )
        self.profit = JsonHttpClient(
            os.getenv("PROFIT_AGENT_URL", "http://localhost:8010"),
            "Profit_Agent",
            timeout_seconds=30,
        )
        self.performance = JsonHttpClient(
            os.getenv("PERFORMANCE_AGENT_URL", "http://localhost:8012"),
            "Performance_Agent",
            timeout_seconds=30,
        )

    def get(self, client: JsonHttpClient, path: str) -> Any:
        return client.request(path, correlation_id=self.correlation_id)

    def post(self, client: JsonHttpClient, path: str, payload: Any) -> Any:
        return client.request(
            path,
            method="POST",
            payload=payload,
            correlation_id=self.correlation_id,
        )


def load_preflight(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeSafetyError("Hourly preflight report is missing or invalid.") from exc
    if report.get("status") != "ready" or not report.get("portfolio_cycle_id"):
        raise RuntimeSafetyError("Hourly preflight did not reach ready state.")
    return report


def wait_for_dependencies(clients: CycleClients, *, paper_automation: bool) -> None:
    required = [
        clients.execution,
        clients.manager,
        clients.technical,
        clients.fundamental,
        clients.market,
        clients.portfolio,
        clients.profit,
        clients.performance,
    ]
    if paper_automation:
        required.append(clients.database)
    for client in required:
        health = clients.get(client, "/health")
        if as_dict(health).get("status") not in {None, "success"}:
            raise RuntimeSafetyError(f"{client.service_name} health contract failed.")
        ready = clients.get(client, "/ready")
        ready_data = as_dict(unwrap(ready))
        if ready_data.get("ready") is False or as_dict(ready).get("status") == "error":
            raise RuntimeSafetyError(f"{client.service_name} is not ready.")


def _broker_state(clients: CycleClients, account_id: str) -> dict[str, Any]:
    return as_dict(
        unwrap(clients.get(clients.execution, f"/broker/state?account_id={account_id}"))
    )


def _reconcile(clients: CycleClients, account_id: str, stage: str) -> dict[str, Any]:
    response = clients.post(
        clients.execution,
        f"/broker/reconcile?account_id={account_id}&push_to_database=true",
        {},
    )
    data = require_safe_broker_sync(response, stage=stage)
    db_status = clients.get(
        clients.database,
        f"/broker-sync/status?account_id={account_id}",
    )
    require_safe_broker_sync(db_status, stage=f"{stage} database verification")
    return data


def _position_payload(row: dict[str, Any]) -> dict[str, Any]:
    quantity = number(row.get("quantity") or row.get("qty"))
    price = number(
        row.get("current_market_price")
        or row.get("current_price")
        or row.get("market_price")
        or row.get("avg_entry_price")
    )
    return {
        "symbol": str(row.get("symbol") or "").upper(),
        "market_value": max(0.0, number(row.get("market_value"), quantity * price)),
        "quantity": max(0.0, quantity),
        "strategy_bucket": row.get("strategy_bucket") or "unassigned",
        "unrealized_pl_pct": number(row.get("unrealized_plpc"), 0.0),
    }


def _performance_fill(row: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(row.get("symbol") or "").upper()
    quantity = number(row.get("quantity"))
    fill_price = number(row.get("fill_price") or row.get("price"))
    if not symbol or quantity <= 0 or fill_price <= 0:
        return None
    return {
        "trade_plan_id": row.get("trade_plan_id"),
        "order_id": row.get("order_id"),
        "trade_id": row.get("trade_id"),
        "symbol": symbol,
        "side": str(row.get("side") or "buy").lower(),
        "quantity": quantity,
        "fill_price": fill_price,
        "fees": max(0.0, number(row.get("fees"))),
        "realized_pnl": number(row.get("realized_pnl")),
        "filled_at": row.get("filled_at") or row.get("executed_at"),
        "metadata": as_dict(row.get("metadata")),
    }


def review_existing_positions(
    clients: CycleClients,
    *,
    preflight: dict[str, Any],
    account_id: str,
    execute_safe_actions: bool,
) -> dict[str, Any]:
    _reconcile(clients, account_id, "pre-analysis")
    state = _broker_state(clients, account_id)
    account = as_dict(state.get("account"))
    positions = as_list(state.get("positions"))
    open_orders = as_list(state.get("open_orders"))
    diagnostics_response = clients.get(
        clients.execution,
        "/broker/protection-diagnostics",
    )
    diagnostics = as_dict(unwrap(diagnostics_response))
    protection_by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in as_list(diagnostics.get("positions"))
    }

    regime_inputs = as_dict(preflight.get("market_regime_inputs"))
    regime = as_dict(
        unwrap(clients.post(clients.market, "/market/regime", regime_inputs))
    )
    strategy = as_dict(
        unwrap(clients.post(clients.market, "/market/strategy", regime_inputs))
    )
    equity = number(account.get("equity") or account.get("portfolio_value"))
    cash = number(account.get("cash"))
    if equity <= 0:
        raise RuntimeSafetyError("Broker account equity must be greater than zero.")
    portfolio = as_dict(
        unwrap(
            clients.post(
                clients.portfolio,
                "/portfolio/allocation",
                {
                    "equity": equity,
                    "cash": cash,
                    "positions": [_position_payload(row) for row in positions],
                    "mode": regime.get("recommended_mode") or "cash_heavy",
                },
            )
        )
    )
    database_fills = as_list(
        unwrap(
            clients.get(
                clients.database,
                f"/accounts/{account_id}/fills?limit=500",
            )
        )
    )
    performance_fills = [
        fill for row in database_fills if (fill := _performance_fill(row))
    ]
    session_risk = as_dict(
        unwrap(
            clients.post(
                clients.performance,
                "/performance/session-risk",
                {
                    "equity": equity,
                    "account_id": account_id,
                    "fills": performance_fills,
                    "emergency_halt": False,
                },
            )
        )
    )
    if session_risk.get("emergency_halt") is True:
        raise RuntimeSafetyError("Performance_Agent session emergency halt is active.")

    db_positions = as_list(
        unwrap(
            clients.get(
                clients.database,
                f"/accounts/{account_id}/positions",
            )
        )
    )
    db_by_symbol = {
        str(row.get("symbol") or "").upper(): row for row in db_positions
    }
    portfolio_by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in as_list(portfolio.get("position_exposure"))
    }
    decisions: list[dict[str, Any]] = []
    for row in positions:
        symbol = str(row.get("symbol") or "").upper()
        quantity = number(row.get("quantity") or row.get("qty"))
        entry = number(row.get("average_cost") or row.get("avg_entry_price"))
        current = number(row.get("current_market_price") or row.get("current_price"))
        if not symbol or quantity <= 0 or entry <= 0 or current <= 0:
            raise RuntimeSafetyError("Broker position contract is incomplete.")
        technical = unwrap(
            clients.post(clients.technical, "/analyze", {"ticker": symbol, "period": "1y", "account_id": account_id})
        )
        fundamental = unwrap(
            clients.post(clients.fundamental, "/analyze", {"ticker": symbol, "period": "1y", "account_id": account_id})
        )
        protection = protection_by_symbol.get(symbol, {})
        stop_orders = as_list(protection.get("stop_orders") or protection.get("protective_orders"))
        stop_price = None
        for order in stop_orders:
            stop_price = number(order.get("stop_price") or order.get("trigger_price")) or stop_price
        durable = db_by_symbol.get(symbol, {})
        highest = number(
            durable.get("highest_price_since_entry"),
            max(entry, current),
        )
        profit_plan = as_dict(
            unwrap(
                clients.post(
                    clients.profit,
                    "/profit/plan",
                    {
                        "position": {
                            "symbol": symbol,
                            "side": "long",
                            "quantity": quantity,
                            "entry_price": entry,
                            "current_price": current,
                            "stop_loss": stop_price or None,
                            "highest_price_since_entry": max(entry, current, highest),
                            "strategy_bucket": durable.get("strategy_bucket") or "unassigned",
                        }
                    },
                )
            )
        )
        action = classify_position_action(
            position=row,
            protection=protection,
            portfolio_position=portfolio_by_symbol.get(symbol, {}),
            profit_plan=profit_plan,
        )
        decisions.append(
            {
                "symbol": symbol,
                "position_lifecycle_id": durable.get("position_lifecycle_id") or durable.get("position_id"),
                "action": action,
                "automatic_execution_allowed": action in {"HOLD", "MOVE_STOP", "REPLACE_PROTECTION"},
                "manual_approval_required": action in {"PARTIAL_EXIT_RECOMMENDATION", "EXIT_ALL_RECOMMENDATION"},
                "protection": protection,
                "profit_plan": profit_plan,
                "portfolio": portfolio_by_symbol.get(symbol, {}),
                "technical": technical,
                "fundamental": fundamental,
                "highest_price_since_entry": max(entry, current, highest),
            }
        )

    stale_cleanup = unwrap(
        clients.post(
            clients.execution,
            (
                "/broker/cleanup/stale-open-orders?max_age_minutes="
                f"{int(os.getenv('STALE_ORDER_MAX_AGE_MINUTES', '390'))}"
                f"&dry_run={'false' if execute_safe_actions else 'true'}"
                "&include_protective=false"
            ),
            {},
        )
    )
    manual_recommendations = [
        row for row in decisions if row["manual_approval_required"]
    ]
    if manual_recommendations:
        clients.post(
            clients.database,
            "/order-review-tickets",
            {
                "ticket_id": f"{preflight['portfolio_cycle_id']}-exit-review",
                "account_id": account_id,
                "correlation_id": preflight["portfolio_cycle_id"],
                "source": "manager-agent-hourly-portfolio-cycle",
                "mode": "manual_approval_ticket",
                "safety": "read_only_no_orders_submitted_no_orders_cancelled",
                "status": "ready_for_manual_approval",
                "approval_required": True,
                "execution_enabled": False,
                "requested_symbols": [row["symbol"] for row in manual_recommendations],
                "ready_count": len(manual_recommendations),
                "orders_submitted": False,
                "orders_cancelled": False,
                "ticket_payload": {"recommendations": manual_recommendations},
            },
        )

    report = {
        "portfolio_cycle_id": preflight["portfolio_cycle_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_mode": preflight["market_mode"],
        "stage": "existing_positions_reviewed_before_candidates",
        "account": {
            "status": account.get("status"),
            "equity_present": equity > 0,
            "position_count": len(positions),
            "open_order_count": len(open_orders),
        },
        "market_regime": regime,
        "market_strategy": strategy,
        "portfolio_allocation": portfolio,
        "performance_session_risk": session_risk,
        "protection_diagnostics": diagnostics,
        "position_decisions": decisions,
        "stale_order_cleanup": stale_cleanup,
        "manual_exit_recommendation_count": len(manual_recommendations),
        "safe_for_candidate_analysis": not protection_gaps(diagnostics_response),
    }
    clients.post(
        clients.database,
        "/review-history",
        {
            "account_id": account_id,
            "review_run_id": preflight["portfolio_cycle_id"],
            "source": "manager-agent-hourly-portfolio-cycle",
            "status": "reviewed",
            "report": report,
        },
    )
    return report


def run_candidate_cycle(
    clients: CycleClients,
    *,
    preflight: dict[str, Any],
    account_id: str,
    review_report: dict[str, Any],
) -> dict[str, Any]:
    market_open = bool(preflight.get("market_open"))
    paper_automation = bool(as_dict(preflight.get("runtime")).get("paper_automation"))
    execute = market_open and paper_automation
    if paper_automation:
        _reconcile(clients, account_id, "pre-execution")
        current_protection = clients.get(
            clients.execution,
            "/broker/protection-diagnostics",
        )
        if protection_gaps(current_protection):
            execute = False
    response = clients.post(
        clients.manager,
        "/discover-analyze-trade",
        {
            "account_id": account_id,
            "max_universe": int(os.getenv("HOURLY_MAX_UNIVERSE", "1000")),
            "top_n": int(os.getenv("HOURLY_TOP_N", "10")),
            "min_final_score": number(os.getenv("HOURLY_MIN_FINAL_SCORE", "0.55"), 0.55),
            "execute": execute,
            "portfolio_cycle_id": preflight["portfolio_cycle_id"],
        },
    )
    response_data = as_dict(unwrap(response))
    execution = as_dict(response_data.get("execution"))
    if execute and execution.get("status") == "failed":
        raise RuntimeSafetyError("Manager execution failed closed.")
    return {
        "execute_requested": execute,
        "market_mode": preflight["market_mode"],
        "manager_response": response,
    }


def finalize_cycle(
    clients: CycleClients,
    *,
    preflight: dict[str, Any],
    account_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    if as_dict(preflight.get("runtime")).get("paper_automation"):
        clients.post(
            clients.execution,
            "/reconciliation/run-once?limit=100",
            {},
        )
        candidate = as_dict(report.get("candidate_cycle"))
        manager_response = as_dict(candidate.get("manager_response"))
        manager_data = as_dict(unwrap(manager_response))
        execution = as_dict(manager_data.get("execution"))
        order_statuses: list[dict[str, Any]] = []
        for created in as_list(execution.get("created")):
            order_id = created.get("order_id")
            if order_id in (None, ""):
                raise RuntimeSafetyError(
                    "Execution response omitted an order ID required for status verification."
                )
            status_response = clients.get(
                clients.execution,
                f"/execute/{order_id}",
            )
            order_statuses.append(as_dict(unwrap(status_response)))
        failed_statuses = {
            "failed",
            "rejected",
            "error",
        }
        if any(
            str(row.get("status") or "").lower().split(".")[-1]
            in failed_statuses
            for row in order_statuses
        ):
            raise RuntimeSafetyError(
                "At least one submitted Paper order reached a failed status."
            )
        reconciliation = _reconcile(clients, account_id, "post-execution")
        diagnostics = clients.get(
            clients.execution,
            "/broker/protection-diagnostics",
        )
        gaps = protection_gaps(diagnostics)
        if gaps:
            raise RuntimeSafetyError(
                "Post-execution protection verification found an unsafe gap."
            )
    else:
        reconciliation = {"status": "simulator_dry_run"}
        diagnostics = {"status": "simulator_dry_run"}
        order_statuses = []
    report.update(
        {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "post_execution_reconciliation": reconciliation,
            "post_execution_protection": unwrap(diagnostics),
            "submitted_order_statuses": order_statuses,
            "partial_fill_detected": any(
                "partial" in str(row.get("status") or "").lower()
                for row in order_statuses
            ),
            "status": "completed",
        }
    )
    clients.post(
        clients.database,
        "/review-history",
        {
            "account_id": account_id,
            "review_run_id": f"{preflight['portfolio_cycle_id']}-final",
            "source": "manager-agent-hourly-portfolio-cycle",
            "status": "completed",
            "report": report,
        },
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("wait", "prepare", "trade", "finalize"))
    parser.add_argument("--preflight", type=Path, default=Path("reports/hourly-preflight.json"))
    parser.add_argument("--review", type=Path, default=Path("reports/hourly-position-review.json"))
    parser.add_argument("--manager", type=Path, default=Path("reports/hourly-manager-cycle.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/hourly-portfolio-cycle.json"))
    return parser.parse_args()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    try:
        preflight = load_preflight(args.preflight)
        cycle_id = str(preflight["portfolio_cycle_id"])
        clients = CycleClients(cycle_id)
        paper_automation = bool(as_dict(preflight.get("runtime")).get("paper_automation"))
        account_id = os.getenv("DEFAULT_ACCOUNT_ID", "1")
        if args.phase == "wait":
            wait_for_dependencies(clients, paper_automation=paper_automation)
            print("All required hourly portfolio dependencies are ready.")
            return 0
        if args.phase == "prepare":
            report = review_existing_positions(
                clients,
                preflight=preflight,
                account_id=account_id,
                execute_safe_actions=paper_automation,
            )
            write_json(args.review, report)
        elif args.phase == "trade":
            review = json.loads(args.review.read_text(encoding="utf-8"))
            report = run_candidate_cycle(
                clients,
                preflight=preflight,
                account_id=account_id,
                review_report=review,
            )
            write_json(args.manager, report)
        else:
            review = json.loads(args.review.read_text(encoding="utf-8"))
            manager = json.loads(args.manager.read_text(encoding="utf-8"))
            report = finalize_cycle(
                clients,
                preflight=preflight,
                account_id=account_id,
                report={"review": review, "candidate_cycle": manager},
            )
            write_json(args.output, report)
        print(f"Hourly portfolio phase {args.phase} completed safely.")
        return 0
    except (RuntimeSafetyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Hourly portfolio phase failed closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
