from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.bucket_profit_review import build_profit_request
from scripts.profit_decision_orchestrator import (
    correlation_id_for_report,
    GatewayError,
    GatewayTimeout,
    ProfitDecisionOrchestrator,
)


DECISION_ID = "profit:account-1:position-42:ACGL:v7:tp1"


def lifecycle_row():
    return {
        "symbol": "ACGL",
        "bucket": "value_rebound",
        "quantity": 10,
        "entry_price": 100,
        "current_price": 108,
        "stop_loss": 96,
        "profit_request": {
            "position": {
                "symbol": "ACGL",
                "quantity": 10,
                "entry_price": 100,
                "current_price": 108,
                "stop_loss": 96,
            },
            "lifecycle": {
                "position_id": "account-1:position-42",
                "position_version": 7,
                "first_target_executed": False,
                "second_target_executed": False,
                "total_exited_quantity": 0,
                "remaining_quantity": 10,
            },
        },
        "profit_plan": {
            "symbol": "ACGL",
            "primary_action": "partial_exit",
            "current_r_multiple": 2,
            "unrealized_pl_pct": 0.08,
            "decision_id": DECISION_ID,
            "decision_type": "first_take_profit",
            "position_version": 7,
            "next_lifecycle_state": {"first_target_executed": True},
            "actions": [
                {
                    "action": "move_stop",
                    "symbol": "ACGL",
                    "quantity": 0,
                    "recommended_stop": 100,
                },
                {
                    "action": "partial_exit",
                    "symbol": "ACGL",
                    "quantity": 3,
                    "reason": "first target",
                },
            ],
            "warnings": [],
            "metadata": {"advisory_only": True},
        },
    }


class FakeGateway:
    def __init__(self, *, risk_approved=True, timeout_after_accept=False):
        self.risk_approved = risk_approved
        self.timeout_after_accept = timeout_after_accept
        self.decision = None
        self.risk_approval = None
        self.order = None
        self.execution_calls = 0
        self.requests = []

    def request(
        self,
        service,
        method,
        path,
        *,
        correlation_id,
        payload=None,
        extra_headers=None,
    ):
        self.requests.append(
            {
                "service": service,
                "method": method,
                "path": path,
                "correlation_id": correlation_id,
                "payload": deepcopy(payload),
                "headers": deepcopy(extra_headers or {}),
            }
        )
        if service == "database" and path.endswith("/profit-decisions/reserve"):
            if self.decision is None:
                self.decision = {
                    **payload,
                    "account_id": "1",
                    "status": "PROPOSED",
                    "executed_quantity": 0,
                    "duplicate": False,
                }
            else:
                self.decision["duplicate"] = True
            return {"data": deepcopy(self.decision)}
        if service == "risk":
            return {
                "data": {
                    "approved": self.risk_approved,
                    "status": "approved" if self.risk_approved else "rejected",
                    "reason": "test risk result",
                }
            }
        if service == "database" and path.startswith("/risk-approvals/"):
            if self.risk_approval is None:
                raise GatewayError("not found", status_code=404)
            return {"data": deepcopy(self.risk_approval)}
        if service == "database" and path == "/risk-approvals":
            self.risk_approval = {**payload, "status": "approved"}
            return {"data": deepcopy(self.risk_approval)}
        if service == "database" and path.endswith("/transition"):
            assert self.decision["status"] == payload["expected_status"]
            self.decision["status"] = payload["status"]
            self.decision["executed_quantity"] = payload.get("executed_quantity", 0)
            self.decision["duplicate"] = False
            return {"data": deepcopy(self.decision)}
        if service == "database" and "/orders/trade/" in path:
            if self.order is None:
                raise GatewayError("not found", status_code=404)
            return {"data": deepcopy(self.order)}
        if service == "execution":
            self.execution_calls += 1
            assert payload["trade_id"] == DECISION_ID
            assert payload["side"] == "sell"
            assert payload["quantity"] == 3
            assert extra_headers == {"Idempotency-Key": DECISION_ID}
            self.order = {
                "order_id": "order-1",
                "trade_id": DECISION_ID,
                "status": "executed",
                "executed_quantity": 3,
            }
            if self.timeout_after_accept:
                self.order["status"] = "placed"
                self.timeout_after_accept = False
                raise GatewayTimeout("response lost after acceptance")
            return {"data": {"order": deepcopy(self.order)}}
        raise AssertionError(f"unexpected request: {service} {method} {path}")


def orchestrator(gateway):
    return ProfitDecisionOrchestrator(
        gateway,
        account_id=1,
        correlation_id="corr-profit-1",
        trading_mode="SIMULATOR",
    )


def test_manager_forwards_database_lifecycle_to_profit_request():
    position = {
        "symbol": "ACGL",
        "account_id": 1,
        "position_id": 42,
        "position_version": 7,
        "quantity": 10,
        "average_cost": 100,
        "current_market_price": 108,
        "highest_price_since_entry": 120,
        "first_target_executed": False,
        "second_target_executed": False,
        "total_exited_quantity": 0,
        "sources": ["database_agent"],
    }

    payload = build_profit_request("value_rebound", position, None)

    assert payload["lifecycle"] == {
        "position_id": "account-1:position-42",
        "position_version": 7,
        "first_target_executed": False,
        "second_target_executed": False,
        "total_exited_quantity": 0,
        "remaining_quantity": 10,
    }


def test_orchestration_reuses_profit_review_correlation_id():
    report = {
        "correlation_id": "profit-review-correlation-1",
        "generated_at": "2026-07-22T00:00:00Z",
        "bucket": "value_rebound",
    }

    assert correlation_id_for_report(report) == "profit-review-correlation-1"


def test_orchestration_derives_stable_correlation_id_for_legacy_report():
    report = {
        "generated_at": "2026-07-22T00:00:00Z",
        "bucket": "value_rebound",
    }

    first = correlation_id_for_report(report)
    second = correlation_id_for_report(report)

    assert first == second
    assert first.startswith("profit-review-")


def test_risk_approved_decision_executes_once_and_marks_fill():
    gateway = FakeGateway()
    manager = orchestrator(gateway)

    first = manager.orchestrate(lifecycle_row())
    retry = manager.orchestrate(lifecycle_row())

    assert first["status"] == "EXECUTED"
    assert first["decision"]["executed_quantity"] == 3
    assert retry["status"] == "DUPLICATE_EXECUTED"
    assert gateway.execution_calls == 1
    assert gateway.decision["status"] == "EXECUTED"
    assert all(
        request["correlation_id"] == "corr-profit-1"
        for request in gateway.requests
    )
    reserve = next(
        request
        for request in gateway.requests
        if request["path"].endswith("/profit-decisions/reserve")
    )
    assert reserve["payload"]["metadata"]["correlation_id"] == "corr-profit-1"


def test_risk_rejection_is_terminal_and_never_calls_execution():
    gateway = FakeGateway(risk_approved=False)
    manager = orchestrator(gateway)

    result = manager.orchestrate(lifecycle_row())
    retry = manager.orchestrate(lifecycle_row())

    assert result["status"] == "REJECTED"
    assert retry["status"] == "DUPLICATE_REJECTED"
    assert gateway.execution_calls == 0


def test_timeout_after_acceptance_is_retried_without_duplicate_submission():
    gateway = FakeGateway(timeout_after_accept=True)
    manager = orchestrator(gateway)

    first = manager.orchestrate(lifecycle_row())
    second = manager.orchestrate(lifecycle_row())

    assert first["status"] == "EXECUTION_PENDING"
    assert first["retry_safe"] is True
    assert second["status"] == "EXECUTION_PENDING"
    assert second["order"]["status"] == "placed"
    assert gateway.execution_calls == 1
    assert gateway.decision["status"] == "EXECUTION_PENDING"


def test_partial_fill_is_recorded_but_target_remains_pending():
    gateway = FakeGateway(timeout_after_accept=True)
    manager = orchestrator(gateway)
    manager.orchestrate(lifecycle_row())
    gateway.order.update({"status": "partially_filled", "executed_quantity": 1})

    result = manager.orchestrate(lifecycle_row())

    assert result["status"] == "EXECUTION_PENDING"
    assert result["decision"]["executed_quantity"] == 1
    assert gateway.execution_calls == 1
    assert gateway.decision["status"] == "EXECUTION_PENDING"


def test_missing_lifecycle_blocks_before_any_external_write():
    gateway = FakeGateway()
    row = lifecycle_row()
    row["profit_request"].pop("lifecycle")

    result = orchestrator(gateway).orchestrate(row)

    assert result["status"] == "BLOCKED_MISSING_IDEMPOTENCY_CONTRACT"
    assert gateway.requests == []


def test_live_mode_is_rejected():
    with pytest.raises(ValueError, match="limited to PAPER or SIMULATOR"):
        ProfitDecisionOrchestrator(
            FakeGateway(),
            account_id=1,
            correlation_id="corr-live",
            trading_mode="LIVE",
        )
