from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from scripts.profit_decision_orchestrator import (
    GatewayTimeout,
    HttpGateway,
    ProfitDecisionOrchestrator,
    ServiceConfig,
)


DEFAULT_QUALITY = {
    "market_price_fresh": True,
    "peak_history_complete": True,
    "position_version_current": True,
}


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def unwrap(value: Dict[str, Any]) -> Any:
    return value.get("data") if isinstance(value, dict) and "data" in value else value


@dataclass(frozen=True)
class PositionCase:
    account_id: int
    symbol: str
    quantity: int = 10
    entry_price: float = 100.0
    current_price: float = 108.0
    stop_loss: float = 96.0
    peak: Optional[float] = 108.0


class TimeoutAfterAcceptGateway:
    """Return a transport timeout after Execution has accepted one request."""

    def __init__(self, delegate: HttpGateway):
        self.delegate = delegate
        self.timed_out = False

    def request(self, service: str, method: str, path: str, **kwargs):
        response = self.delegate.request(service, method, path, **kwargs)
        if (
            service == "execution"
            and method == "POST"
            and path == "/execute"
            and not self.timed_out
        ):
            self.timed_out = True
            raise GatewayTimeout("simulated response timeout after acceptance")
        return response


class ProfitLifecycleE2E:
    def __init__(
        self,
        *,
        database_url: str,
        database_api_key: str,
        profit_url: str,
        profit_api_key: str,
        risk_url: str,
        execution_url: str,
        execution_api_key: str,
        compose_directory: Path,
        compose_files: list[Path],
        output_path: Path,
    ):
        self.gateway = HttpGateway(
            {
                "database": ServiceConfig(database_url, database_api_key),
                "profit": ServiceConfig(profit_url, profit_api_key),
                "risk": ServiceConfig(risk_url),
                "execution": ServiceConfig(execution_url, execution_api_key),
            },
            timeout=30,
        )
        self.compose_directory = compose_directory
        self.compose_files = compose_files
        self.output_path = output_path
        self.current_scenario: Optional[str] = None
        self.report: Dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "services": {},
            "scenarios": [],
        }

    def request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        correlation_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.gateway.request(
            service,
            method,
            path,
            correlation_id=correlation_id,
            payload=payload,
        )

    def scenario(self, name: str, callback: Callable[[], Dict[str, Any]]) -> None:
        self.current_scenario = name
        started = datetime.now(timezone.utc)
        try:
            evidence = callback()
        except Exception as exc:
            self.report["scenarios"].append(
                {
                    "name": name,
                    "status": "failed",
                    "error": str(exc),
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            raise
        self.report["scenarios"].append(
            {
                "name": name,
                "status": "passed",
                "evidence": evidence,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.current_scenario = None

    def write_report(self, *, status: str, error: Optional[str] = None) -> None:
        self.report["status"] = status
        self.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        if error:
            self.report["error"] = error
            self.report["failed_scenario"] = self.current_scenario
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(self.report, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def record_service_contracts(self) -> None:
        for service in ("database", "profit", "risk", "execution"):
            correlation_id = f"profit-e2e-contract-{service}"
            response = self.request(
                service,
                "GET",
                "/version",
                correlation_id=correlation_id,
            )
            data = unwrap(response) or {}
            self.report["services"][service] = {
                "version": response.get("version") or data.get("version"),
                "schema_version": response.get("schema_version")
                or data.get("schema_version"),
            }

    def sync_position(self, case: PositionCase) -> None:
        correlation_id = f"profit-e2e-seed-{case.account_id}"

        def snapshot(current_price: float) -> Dict[str, Any]:
            return {
                "source": "full_system_profit_e2e",
                "account_id": case.account_id,
                "broker": "SIMULATOR",
                "paper": True,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "account": {
                    "cash": "100000",
                    "buying_power": "100000",
                    "equity": "100000",
                    "status": "ACTIVE",
                },
                "positions": [
                    {
                        "symbol": case.symbol,
                        "qty": str(case.quantity),
                        "avg_entry_price": str(case.entry_price),
                        "current_price": str(current_price),
                        "market_value": str(case.quantity * current_price),
                        "strategy_bucket": "value_rebound",
                    }
                ],
                "open_orders": [],
                "summary": {
                    "position_count": 1,
                    "open_order_count": 0,
                },
            }

        if case.peak is not None and case.peak > case.current_price:
            self.request(
                "database",
                "POST",
                "/broker-sync",
                correlation_id=correlation_id,
                payload=snapshot(case.peak),
            )
        response = self.request(
            "database",
            "POST",
            "/broker-sync",
            correlation_id=correlation_id,
            payload=snapshot(case.current_price),
        )
        result = unwrap(response) or {}
        require(
            result.get("positions_synced") == 1, "broker sync did not seed one position"
        )

    def lifecycle(self, account_id: int, symbol: str) -> Dict[str, Any]:
        response = self.request(
            "database",
            "GET",
            f"/accounts/{account_id}/profit-lifecycles",
            correlation_id=f"profit-e2e-lifecycle-{account_id}",
        )
        rows = unwrap(response) or []
        matches = [
            row
            for row in rows
            if str(row.get("symbol") or "").upper() == symbol.upper()
        ]
        require(
            len(matches) == 1,
            f"expected one lifecycle for {symbol}, got {len(matches)}",
        )
        return matches[0]

    def profit_payload(
        self,
        case: PositionCase,
        lifecycle: Dict[str, Any],
        *,
        include_peak: bool = True,
        quality: Optional[Dict[str, bool]] = DEFAULT_QUALITY,
    ) -> Dict[str, Any]:
        position = {
            "symbol": case.symbol,
            "quantity": case.quantity,
            "entry_price": case.entry_price,
            "current_price": case.current_price,
            "stop_loss": case.stop_loss,
        }
        if include_peak and case.peak is not None:
            position["highest_price_since_entry"] = case.peak
        payload: Dict[str, Any] = {
            "schema_version": "profit-decision.v2",
            "position": position,
            "lifecycle": {
                "position_id": lifecycle["position_id"],
                "position_version": lifecycle["position_version"],
                "first_target_executed": lifecycle["first_target_executed"],
                "second_target_executed": lifecycle["second_target_executed"],
                "total_exited_quantity": lifecycle["total_exited_quantity"],
                "remaining_quantity": lifecycle["remaining_quantity"],
            },
            "first_take_profit_r": 2,
            "second_take_profit_r": 3,
            "partial_exit_pct": 0.3,
            "trailing_stop_pct": 0.08,
            "break_even_trigger_r": 1,
            "market_constraints": {
                "price_increment": "0.01",
                "quantity_increment": "1",
                "minimum_order_quantity": "1",
            },
        }
        if quality is not None:
            payload["data_quality"] = quality
        return payload

    def profit_plan(
        self,
        case: PositionCase,
        lifecycle: Dict[str, Any],
        correlation_id: str,
        **payload_options,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        payload = self.profit_payload(case, lifecycle, **payload_options)
        response = self.request(
            "profit",
            "POST",
            "/profit/plan",
            correlation_id=correlation_id,
            payload=payload,
        )
        require(
            response.get("status") == "success", "Profit Agent did not return success"
        )
        require(
            response.get("correlation_id") == correlation_id,
            "Profit Agent did not echo the correlation ID",
        )
        plan = unwrap(response) or {}
        return payload, plan

    @staticmethod
    def row(
        case: PositionCase,
        payload: Dict[str, Any],
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "symbol": case.symbol,
            "bucket": "value_rebound",
            "quantity": case.quantity,
            "entry_price": case.entry_price,
            "current_price": case.current_price,
            "stop_loss": case.stop_loss,
            "profit_request": payload,
            "profit_plan": plan,
        }

    def manager(
        self,
        *,
        account_id: int,
        correlation_id: str,
        allow_exit_all: bool = False,
        gateway=None,
    ) -> ProfitDecisionOrchestrator:
        return ProfitDecisionOrchestrator(
            gateway or self.gateway,
            account_id=account_id,
            correlation_id=correlation_id,
            trading_mode="SIMULATOR",
            allow_exit_all=allow_exit_all,
        )

    def database_order(self, decision_id: str, correlation_id: str) -> Dict[str, Any]:
        encoded = urllib.parse.quote(decision_id, safe="")
        response = self.request(
            "database",
            "GET",
            f"/orders/trade/{encoded}",
            correlation_id=correlation_id,
        )
        return unwrap(response) or {}

    def decision(
        self,
        account_id: int,
        decision_id: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        encoded = urllib.parse.quote(decision_id, safe="")
        response = self.request(
            "database",
            "GET",
            f"/accounts/{account_id}/profit-decisions/{encoded}",
            correlation_id=correlation_id,
        )
        return unwrap(response) or {}

    def orders(self, account_id: int, correlation_id: str) -> list[Dict[str, Any]]:
        response = self.request(
            "database",
            "GET",
            f"/accounts/{account_id}/orders",
            correlation_id=correlation_id,
        )
        return unwrap(response) or []

    def run_worker(self) -> str:
        command = ["docker", "compose"]
        for compose_file in self.compose_files:
            command.extend(["-f", str(compose_file)])
        command.extend(
            [
                "exec",
                "-T",
                "-e",
                "WORKER_RUN_ONCE=true",
                "execution-agent",
                "/opt/venv/bin/python",
                "-m",
                "app.workers.execution_worker",
            ]
        )
        completed = subprocess.run(
            command,
            cwd=self.compose_directory,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        output = f"{completed.stdout}\n{completed.stderr}".strip()
        require(completed.returncode == 0, f"Execution worker failed: {output}")
        return output[-2000:]

    def complete_execution(
        self,
        *,
        case: PositionCase,
        row: Dict[str, Any],
        correlation_id: str,
        allow_exit_all: bool = False,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        manager = self.manager(
            account_id=case.account_id,
            correlation_id=correlation_id,
            allow_exit_all=allow_exit_all,
        )
        submitted = manager.orchestrate(row)
        require(
            submitted.get("status") == "EXECUTION_PENDING",
            f"expected EXECUTION_PENDING, got {submitted}",
        )
        self.run_worker()
        completed = manager.orchestrate(row)
        require(
            completed.get("status") == "EXECUTED",
            f"expected EXECUTED, got {completed}",
        )
        decision_id = row["profit_plan"]["decision_id"]
        order = self.database_order(decision_id, correlation_id)
        require(
            str(order.get("status")).lower() == "executed", "order was not executed"
        )
        self.assert_trace(
            case.account_id,
            decision_id,
            correlation_id,
            order,
        )
        return completed, order

    def assert_trace(
        self,
        account_id: int,
        decision_id: str,
        correlation_id: str,
        order: Dict[str, Any],
    ) -> None:
        decision = self.decision(account_id, decision_id, correlation_id)
        require(
            decision.get("correlation_id") == correlation_id,
            "Database decision lost the originating correlation ID",
        )
        require(
            (decision.get("metadata") or {}).get("last_transition_correlation_id")
            == correlation_id,
            "Database decision transition lost the correlation ID",
        )
        require(
            (order.get("metadata") or {}).get("correlation_id") == correlation_id,
            "Execution order lost the correlation ID",
        )
        approval_id = order.get("risk_approval_id")
        require(approval_id, "Execution order has no risk approval ID")
        response = self.request(
            "database",
            "GET",
            f"/risk-approvals/{urllib.parse.quote(str(approval_id), safe='')}",
            correlation_id=correlation_id,
        )
        approval = unwrap(response) or {}
        require(
            (approval.get("metadata") or {}).get("correlation_id") == correlation_id,
            "Risk approval lost the correlation ID",
        )

    def run(self) -> None:
        self.record_service_contracts()

        def hold_scenario() -> Dict[str, Any]:
            case = PositionCase(101, "HOLD", current_price=101, peak=101)
            self.sync_position(case)
            lifecycle = self.lifecycle(case.account_id, case.symbol)
            correlation_id = "profit-e2e-hold"
            payload, plan = self.profit_plan(case, lifecycle, correlation_id)
            require(
                plan.get("primary_action") == "hold", f"unexpected hold plan: {plan}"
            )
            result = self.manager(
                account_id=case.account_id,
                correlation_id=correlation_id,
            ).orchestrate(self.row(case, payload, plan))
            require(result.get("status") == "NO_EXECUTION_REQUIRED", str(result))
            require(
                self.orders(case.account_id, correlation_id) == [],
                "hold created an order",
            )
            return {"primary_action": "hold", "orders": 0}

        self.scenario("hold_no_execution", hold_scenario)

        def full_exit_scenario(
            case: PositionCase,
            correlation_id: str,
            expected_trigger: str,
        ) -> Dict[str, Any]:
            self.sync_position(case)
            lifecycle = self.lifecycle(case.account_id, case.symbol)
            payload, plan = self.profit_plan(case, lifecycle, correlation_id)
            require(plan.get("primary_action") == "exit_all", str(plan))
            require(plan.get("trigger") == expected_trigger, str(plan))
            completed, order = self.complete_execution(
                case=case,
                row=self.row(case, payload, plan),
                correlation_id=correlation_id,
                allow_exit_all=True,
            )
            return {
                "trigger": expected_trigger,
                "decision_id": plan["decision_id"],
                "order_id": order["order_id"],
                "decision_status": completed["status"],
            }

        self.scenario(
            "hard_stop_exit",
            lambda: full_exit_scenario(
                PositionCase(102, "HARD", current_price=96, peak=120),
                "profit-e2e-hard-stop",
                "hard_stop_loss_breach",
            ),
        )
        self.scenario(
            "trailing_stop_exit",
            lambda: full_exit_scenario(
                PositionCase(
                    103,
                    "TRAIL",
                    current_price=108,
                    stop_loss=94,
                    peak=120,
                ),
                "profit-e2e-trailing-stop",
                "trailing_stop_breach",
            ),
        )

        def targets_scenario() -> Dict[str, Any]:
            first_case = PositionCase(104, "TARGET", current_price=108, peak=108)
            self.sync_position(first_case)
            lifecycle_v1 = self.lifecycle(first_case.account_id, first_case.symbol)
            correlation_id = "profit-e2e-targets"
            payload_v1, plan_v1 = self.profit_plan(
                first_case,
                lifecycle_v1,
                correlation_id,
            )
            require(plan_v1.get("decision_type") == "first_take_profit", str(plan_v1))
            _, first_order = self.complete_execution(
                case=first_case,
                row=self.row(first_case, payload_v1, plan_v1),
                correlation_id=correlation_id,
            )

            duplicate = self.manager(
                account_id=first_case.account_id,
                correlation_id=correlation_id,
            ).orchestrate(self.row(first_case, payload_v1, plan_v1))
            require(duplicate.get("status") == "DUPLICATE_EXECUTED", str(duplicate))
            first_orders = self.orders(first_case.account_id, correlation_id)
            require(
                len(
                    [
                        row
                        for row in first_orders
                        if row.get("trade_id") == plan_v1["decision_id"]
                    ]
                )
                == 1,
                "duplicate retry created another TP1 order",
            )

            second_case = PositionCase(
                104,
                "TARGET",
                quantity=7,
                current_price=112,
                peak=112,
            )
            self.sync_position(second_case)
            lifecycle_v2 = self.lifecycle(second_case.account_id, second_case.symbol)
            require(lifecycle_v2.get("position_version") == 2, str(lifecycle_v2))
            require(
                lifecycle_v2.get("first_target_executed") is True, str(lifecycle_v2)
            )
            payload_v2, plan_v2 = self.profit_plan(
                second_case,
                lifecycle_v2,
                correlation_id,
            )
            require(plan_v2.get("decision_type") == "second_take_profit", str(plan_v2))
            _, second_order = self.complete_execution(
                case=second_case,
                row=self.row(second_case, payload_v2, plan_v2),
                correlation_id=correlation_id,
            )
            final_lifecycle = self.lifecycle(second_case.account_id, second_case.symbol)
            require(final_lifecycle.get("position_version") == 3, str(final_lifecycle))
            require(
                final_lifecycle.get("first_target_executed") is True,
                str(final_lifecycle),
            )
            require(
                final_lifecycle.get("second_target_executed") is True,
                str(final_lifecycle),
            )
            return {
                "tp1_decision_id": plan_v1["decision_id"],
                "tp1_order_id": first_order["order_id"],
                "tp2_decision_id": plan_v2["decision_id"],
                "tp2_order_id": second_order["order_id"],
                "duplicate_status": duplicate["status"],
                "position_version": final_lifecycle["position_version"],
            }

        self.scenario("tp1_tp2_and_duplicate_retry", targets_scenario)

        def stale_version_scenario() -> Dict[str, Any]:
            case = PositionCase(105, "STALE", current_price=108, peak=108)
            self.sync_position(case)
            lifecycle = self.lifecycle(case.account_id, case.symbol)
            stale_lifecycle = {
                **lifecycle,
                "position_version": lifecycle["position_version"] + 1,
            }
            correlation_id = "profit-e2e-stale-version"
            payload, plan = self.profit_plan(case, stale_lifecycle, correlation_id)
            result = self.manager(
                account_id=case.account_id,
                correlation_id=correlation_id,
            ).orchestrate(self.row(case, payload, plan))
            require(
                result.get("status") == "BLOCKED_STALE_POSITION_VERSION", str(result)
            )
            require(
                self.orders(case.account_id, correlation_id) == [],
                "stale version created an order",
            )
            return {
                "status": result["status"],
                "database_version": lifecycle["position_version"],
            }

        self.scenario("stale_position_version", stale_version_scenario)

        def missing_peak_scenario() -> Dict[str, Any]:
            case = PositionCase(106, "MISSING", current_price=108, peak=None)
            self.sync_position(case)
            lifecycle = self.lifecycle(case.account_id, case.symbol)
            correlation_id = "profit-e2e-missing-peak"
            _, plan = self.profit_plan(
                case,
                lifecycle,
                correlation_id,
                include_peak=False,
                quality={**DEFAULT_QUALITY, "peak_history_complete": False},
            )
            require(plan.get("primary_action") == "review", str(plan))
            require(plan.get("decision_status") == "blocked", str(plan))
            require(plan.get("decision_id") is None, str(plan))
            return {
                "primary_action": plan["primary_action"],
                "decision_status": plan["decision_status"],
            }

        self.scenario("missing_peak_is_blocked", missing_peak_scenario)

        def invalid_peak_scenario() -> Dict[str, Any]:
            case = PositionCase(107, "BADPEAK", current_price=108, peak=107)
            self.sync_position(
                PositionCase(
                    case.account_id,
                    case.symbol,
                    current_price=case.current_price,
                    peak=case.current_price,
                )
            )
            lifecycle = self.lifecycle(case.account_id, case.symbol)
            correlation_id = "profit-e2e-invalid-peak"
            try:
                self.profit_plan(case, lifecycle, correlation_id)
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                require(status_code == 422, f"expected Profit 422, got {exc}")
                require("validation_error" in str(exc), str(exc))
                return {"http_status": 422, "error_code": "validation_error"}
            raise AssertionError("Profit Agent accepted a peak below current price")

        self.scenario("invalid_peak_is_rejected", invalid_peak_scenario)

        def risk_rejection_scenario() -> Dict[str, Any]:
            case = PositionCase(108, "RISKREJ", current_price=108, peak=108)
            self.sync_position(case)
            lifecycle = self.lifecycle(case.account_id, case.symbol)
            correlation_id = "profit-e2e-risk-rejection"
            payload, plan = self.profit_plan(case, lifecycle, correlation_id)
            plan["current_r_multiple"] = 0.4
            result = self.manager(
                account_id=case.account_id,
                correlation_id=correlation_id,
            ).orchestrate(self.row(case, payload, plan))
            require(result.get("status") == "REJECTED", str(result))
            require(
                self.orders(case.account_id, correlation_id) == [],
                "Risk rejection created an order",
            )
            decision = self.decision(
                case.account_id,
                plan["decision_id"],
                correlation_id,
            )
            return {
                "status": decision["status"],
                "error": decision["error"],
            }

        self.scenario("risk_rejection", risk_rejection_scenario)

        def timeout_retry_scenario() -> Dict[str, Any]:
            case = PositionCase(109, "TIMEOUT", current_price=108, peak=108)
            self.sync_position(case)
            lifecycle = self.lifecycle(case.account_id, case.symbol)
            correlation_id = "profit-e2e-timeout"
            payload, plan = self.profit_plan(case, lifecycle, correlation_id)
            row = self.row(case, payload, plan)
            timeout_gateway = TimeoutAfterAcceptGateway(self.gateway)
            first = self.manager(
                account_id=case.account_id,
                correlation_id=correlation_id,
                gateway=timeout_gateway,
            ).orchestrate(row)
            require(first.get("status") == "EXECUTION_PENDING", str(first))
            require(first.get("retry_safe") is True, str(first))
            require(timeout_gateway.timed_out, "timeout injection was not exercised")
            before = self.orders(case.account_id, correlation_id)
            require(
                len(before) == 1,
                "timeout-after-accept did not persist exactly one order",
            )
            self.run_worker()
            completed = self.manager(
                account_id=case.account_id,
                correlation_id=correlation_id,
            ).orchestrate(row)
            require(completed.get("status") == "EXECUTED", str(completed))
            after = self.orders(case.account_id, correlation_id)
            require(len(after) == 1, "timeout retry created a duplicate order")
            self.assert_trace(
                case.account_id,
                plan["decision_id"],
                correlation_id,
                after[0],
            )
            return {
                "first_status": first["status"],
                "final_status": completed["status"],
                "orders": len(after),
            }

        self.scenario("retry_after_timeout", timeout_retry_scenario)

        def execution_failure_scenario() -> Dict[str, Any]:
            case = PositionCase(110, "FAIL", current_price=108, peak=108)
            self.sync_position(case)
            lifecycle = self.lifecycle(case.account_id, case.symbol)
            correlation_id = "profit-e2e-execution-failure"
            payload, plan = self.profit_plan(case, lifecycle, correlation_id)
            row = self.row(case, payload, plan)
            manager = self.manager(
                account_id=case.account_id,
                correlation_id=correlation_id,
            )
            submitted = manager.orchestrate(row)
            require(submitted.get("status") == "EXECUTION_PENDING", str(submitted))
            self.run_worker()
            failed = manager.orchestrate(row)
            require(failed.get("status") == "FAILED", str(failed))
            order = self.database_order(plan["decision_id"], correlation_id)
            require(str(order.get("status")).lower() == "failed", str(order))
            return {
                "decision_status": failed["status"],
                "order_status": order["status"],
            }

        self.scenario("execution_failure", execution_failure_scenario)

        def partial_fill_scenario() -> Dict[str, Any]:
            case = PositionCase(111, "PARTIAL", current_price=108, peak=108)
            self.sync_position(case)
            lifecycle = self.lifecycle(case.account_id, case.symbol)
            correlation_id = "profit-e2e-partial-fill"
            payload, plan = self.profit_plan(case, lifecycle, correlation_id)
            row = self.row(case, payload, plan)
            manager = self.manager(
                account_id=case.account_id,
                correlation_id=correlation_id,
            )
            submitted = manager.orchestrate(row)
            require(submitted.get("status") == "EXECUTION_PENDING", str(submitted))
            order = self.database_order(plan["decision_id"], correlation_id)
            order_id = order["order_id"]
            self.request(
                "database",
                "PATCH",
                f"/orders/{order_id}",
                correlation_id=correlation_id,
                payload={
                    "status": "partially_filled",
                    "executed_quantity": 1,
                    "avg_execution_price": case.current_price,
                    "broker_order_id": "e2e-partial-fill",
                },
            )
            partial = manager.orchestrate(row)
            require(partial.get("status") == "EXECUTION_PENDING", str(partial))
            partial_decision = self.decision(
                case.account_id,
                plan["decision_id"],
                correlation_id,
            )
            lifecycle_pending = self.lifecycle(case.account_id, case.symbol)
            require(
                partial_decision.get("executed_quantity") == 1, str(partial_decision)
            )
            require(
                lifecycle_pending.get("position_version") == 1, str(lifecycle_pending)
            )
            require(
                lifecycle_pending.get("first_target_executed") is False,
                str(lifecycle_pending),
            )

            proposed_quantity = int(float(partial_decision["proposed_quantity"]))
            self.request(
                "database",
                "PATCH",
                f"/orders/{order_id}",
                correlation_id=correlation_id,
                payload={
                    "status": "executed",
                    "executed_quantity": proposed_quantity,
                    "avg_execution_price": case.current_price,
                },
            )
            completed = manager.orchestrate(row)
            require(completed.get("status") == "EXECUTED", str(completed))
            lifecycle_complete = self.lifecycle(case.account_id, case.symbol)
            require(
                lifecycle_complete.get("position_version") == 2, str(lifecycle_complete)
            )
            require(
                lifecycle_complete.get("first_target_executed") is True,
                str(lifecycle_complete),
            )
            final_orders = self.orders(case.account_id, correlation_id)
            require(len(final_orders) == 1, "partial-fill retry created another order")
            return {
                "partial_executed_quantity": 1,
                "final_executed_quantity": proposed_quantity,
                "position_version_before_full_fill": lifecycle_pending[
                    "position_version"
                ],
                "position_version_after_full_fill": lifecycle_complete[
                    "position_version"
                ],
                "orders": len(final_orders),
            }

        self.scenario("partial_fill_lifecycle", partial_fill_scenario)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the real Profit → Database → Risk → Execution lifecycle."
    )
    parser.add_argument("--database-url", default="http://localhost:8004")
    parser.add_argument("--database-api-key", required=True)
    parser.add_argument("--profit-url", default="http://localhost:8011")
    parser.add_argument("--profit-api-key", required=True)
    parser.add_argument("--risk-url", default="http://localhost:8007")
    parser.add_argument("--execution-url", default="http://localhost:8006")
    parser.add_argument("--execution-api-key", required=True)
    parser.add_argument("--compose-directory", type=Path, default=Path.cwd())
    parser.add_argument(
        "--compose-file",
        action="append",
        dest="compose_files",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("reports/full-system-profit-e2e.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = ProfitLifecycleE2E(
        database_url=args.database_url,
        database_api_key=args.database_api_key,
        profit_url=args.profit_url,
        profit_api_key=args.profit_api_key,
        risk_url=args.risk_url,
        execution_url=args.execution_url,
        execution_api_key=args.execution_api_key,
        compose_directory=args.compose_directory.resolve(),
        compose_files=[path.resolve() for path in args.compose_files],
        output_path=args.output_json,
    )
    try:
        runner.run()
    except Exception as exc:
        runner.write_report(status="failed", error=str(exc))
        print(f"Full-system Profit E2E failed: {exc}", file=sys.stderr)
        return 1
    runner.write_report(status="passed")
    print(json.dumps(runner.report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
