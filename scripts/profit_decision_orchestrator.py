from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


EXIT_ACTIONS = {"partial_exit", "exit_all"}
FILLED_STATUSES = {"executed", "filled", "succeeded"}
FAILED_STATUSES = {"failed", "rejected", "cancelled", "canceled", "expired"}
PARTIAL_FILL_STATUSES = {"partially_filled", "partial_fill"}


class GatewayError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GatewayTimeout(GatewayError):
    pass


@dataclass(frozen=True)
class ServiceConfig:
    base_url: str
    api_key: Optional[str] = None


class HttpGateway:
    def __init__(self, services: Dict[str, ServiceConfig], timeout: int = 30):
        self.services = services
        self.timeout = timeout

    def request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        correlation_id: str,
        payload: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        config = self.services[service]
        headers = {
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if config.api_key:
            headers["X-API-KEY"] = config.api_key
        headers.update(extra_headers or {})
        request = urllib.request.Request(
            f"{config.base_url.rstrip('/')}{path}",
            data=(
                json.dumps(payload, default=str).encode("utf-8")
                if payload is not None
                else None
            ),
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GatewayError(
                f"{service} returned HTTP {exc.code}: {body}",
                status_code=exc.code,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise GatewayTimeout(f"{service} request timed out") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise GatewayTimeout(f"{service} request timed out") from exc
            raise GatewayError(f"{service} request failed: {exc.reason}") from exc


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def _action_for_primary(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    primary = str(plan.get("primary_action") or "").lower()
    for action in plan.get("actions") or []:
        if isinstance(action, dict) and str(action.get("action") or "").lower() == primary:
            return action
    return None


def _risk_approval_id(decision_id: str) -> str:
    digest = hashlib.sha256(decision_id.encode("utf-8")).hexdigest()[:32]
    return f"profit-risk-{digest}"


def _order_payload(
    *,
    row: Dict[str, Any],
    action: Dict[str, Any],
    decision_id: str,
    risk_approval_id: str,
    account_id: str,
    correlation_id: str,
) -> Dict[str, Any]:
    quantity_value = float(action.get("quantity") or 0)
    if quantity_value <= 0 or not quantity_value.is_integer():
        raise ValueError(
            "PR2 execution supports positive whole-share quantities; "
            "fractional quantities are introduced by the Decimal/tick-size PR"
        )
    quantity = int(quantity_value)
    return {
        "trade_id": decision_id,
        "account_id": account_id,
        "symbol": str(row.get("symbol") or action.get("symbol") or "").upper(),
        "side": "sell",
        "order_type": "market",
        "quantity": quantity,
        "time_in_force": "GTC",
        "strategy_bucket": row.get("bucket") or "unassigned",
        "risk_approval_id": risk_approval_id,
        "final_quantity": quantity,
        "protective_exit": {
            "type": "profit_lifecycle_exit",
            "reduce_only_intent": True,
            "decision_id": decision_id,
        },
        "metadata": {
            "profit_decision_id": decision_id,
            "position_id": ((row.get("profit_request") or {}).get("lifecycle") or {}).get("position_id"),
            "position_version": (row.get("profit_plan") or {}).get("position_version"),
            "correlation_id": correlation_id,
            "advisory_source": "profit-agent",
        },
    }


class ProfitDecisionOrchestrator:
    def __init__(
        self,
        gateway,
        *,
        account_id: str | int,
        correlation_id: str,
        trading_mode: str = "PAPER",
        allow_exit_all: bool = False,
    ):
        mode = trading_mode.strip().upper()
        if mode not in {"PAPER", "SIMULATOR"}:
            raise ValueError("profit decision execution is limited to PAPER or SIMULATOR")
        self.gateway = gateway
        self.account_id = str(account_id)
        self.correlation_id = correlation_id
        self.trading_mode = mode
        self.allow_exit_all = allow_exit_all

    def _request(
        self,
        service: str,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return self.gateway.request(
            service,
            method,
            path,
            correlation_id=self.correlation_id,
            payload=payload,
            extra_headers=extra_headers,
        )

    def _transition(
        self,
        decision_id: str,
        expected_status: str,
        status: str,
        *,
        executed_quantity: float = 0,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        encoded = urllib.parse.quote(decision_id, safe="")
        response = self._request(
            "database",
            "POST",
            f"/accounts/{self.account_id}/profit-decisions/{encoded}/transition",
            {
                "expected_status": expected_status,
                "status": status,
                "executed_quantity": executed_quantity,
                "error": error,
                "metadata": metadata or {},
            },
        )
        return _unwrap(response) or {}

    def _reserve(
        self,
        row: Dict[str, Any],
        action: Dict[str, Any],
    ) -> Dict[str, Any]:
        plan = row.get("profit_plan") or {}
        lifecycle = (row.get("profit_request") or {}).get("lifecycle") or {}
        payload = {
            "position_id": lifecycle.get("position_id"),
            "position_version": plan.get("position_version"),
            "decision_id": plan.get("decision_id"),
            "decision_type": plan.get("decision_type"),
            "proposed_quantity": action.get("quantity"),
            "next_lifecycle_state": plan.get("next_lifecycle_state") or {},
            "metadata": {
                "symbol": row.get("symbol"),
                "bucket": row.get("bucket"),
                "advisory_only": True,
            },
        }
        response = self._request(
            "database",
            "POST",
            f"/accounts/{self.account_id}/profit-decisions/reserve",
            payload,
        )
        return _unwrap(response) or {}

    def _risk_gate(self, row: Dict[str, Any]) -> Dict[str, Any]:
        profit_request = row.get("profit_request") or {}
        position = profit_request.get("position") or {}
        response = self._request(
            "risk",
            "POST",
            "/risk/profit-plan-gate",
            {
                "position": {
                    "symbol": row.get("symbol") or position.get("symbol"),
                    "side": "long",
                    "quantity": position.get("quantity") or row.get("quantity"),
                    "entry_price": position.get("entry_price") or row.get("entry_price"),
                    "current_price": position.get("current_price") or row.get("current_price"),
                    "stop_loss": position.get("stop_loss") or row.get("stop_loss"),
                    "strategy_bucket": row.get("bucket") or "unassigned",
                },
                "profit_plan": row.get("profit_plan") or {},
                "trading_mode": "PAPER",
                "require_manual_exit_all": not self.allow_exit_all,
            },
        )
        return _unwrap(response) or {}

    def _ensure_risk_approval(
        self,
        *,
        row: Dict[str, Any],
        action: Dict[str, Any],
        decision_id: str,
        risk_result: Dict[str, Any],
    ) -> str:
        approval_id = _risk_approval_id(decision_id)
        encoded = urllib.parse.quote(approval_id, safe="")
        try:
            existing = self._request(
                "database", "GET", f"/risk-approvals/{encoded}"
            )
            if (_unwrap(existing) or {}).get("status") == "approved":
                return approval_id
        except GatewayError as exc:
            if exc.status_code != 404:
                raise
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        self._request(
            "database",
            "POST",
            "/risk-approvals",
            {
                "approval_id": approval_id,
                "account_id": self.account_id,
                "symbol": str(row.get("symbol") or "").upper(),
                "side": "sell",
                "approved_quantity": int(float(action.get("quantity") or 0)),
                "expires_at": expires_at.isoformat(),
                "metadata": {
                    "source": "risk_agent_profit_plan_gate",
                    "profit_decision_id": decision_id,
                    "risk_result": risk_result,
                    "correlation_id": self.correlation_id,
                },
            },
        )
        return approval_id

    def _database_order(self, decision_id: str) -> Optional[Dict[str, Any]]:
        encoded = urllib.parse.quote(decision_id, safe="")
        try:
            response = self._request(
                "database", "GET", f"/orders/trade/{encoded}"
            )
        except GatewayError as exc:
            if exc.status_code == 404:
                return None
            raise
        data = _unwrap(response)
        return data if isinstance(data, dict) else None

    def _complete_from_order(
        self,
        decision: Dict[str, Any],
        order: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not order:
            return None
        status = str(order.get("status") or "").lower()
        if status in PARTIAL_FILL_STATUSES:
            quantity = float(
                order.get("executed_quantity") or order.get("filled_qty") or 0
            )
            if quantity > 0:
                return self._transition(
                    decision["decision_id"],
                    "EXECUTION_PENDING",
                    "EXECUTION_PENDING",
                    executed_quantity=quantity,
                    metadata={
                        "order_id": order.get("order_id"),
                        "partial_fill": True,
                    },
                )
            return None
        if status in FILLED_STATUSES:
            quantity = float(
                order.get("executed_quantity")
                or order.get("filled_qty")
                or order.get("quantity")
                or 0
            )
            return self._transition(
                decision["decision_id"],
                "EXECUTION_PENDING",
                "EXECUTED",
                executed_quantity=quantity,
                metadata={"order_id": order.get("order_id"), "broker_confirmed": True},
            )
        if status in FAILED_STATUSES:
            return self._transition(
                decision["decision_id"],
                "EXECUTION_PENDING",
                "FAILED",
                error=str(order.get("reason") or f"execution status {status}"),
                metadata={"order_id": order.get("order_id")},
            )
        return None

    def orchestrate(self, row: Dict[str, Any]) -> Dict[str, Any]:
        plan = row.get("profit_plan") or {}
        action = _action_for_primary(plan)
        primary = str(plan.get("primary_action") or "hold").lower()
        decision_id = str(plan.get("decision_id") or "")
        if primary not in EXIT_ACTIONS:
            return {"status": "NO_EXECUTION_REQUIRED", "action": primary}
        if primary == "exit_all" and not self.allow_exit_all:
            return {"status": "BLOCKED_MANUAL_EXIT_ALL", "action": primary}
        if not action or not decision_id or not plan.get("position_version"):
            return {
                "status": "BLOCKED_MISSING_IDEMPOTENCY_CONTRACT",
                "action": primary,
            }
        lifecycle = (row.get("profit_request") or {}).get("lifecycle") or {}
        if not lifecycle.get("position_id"):
            return {
                "status": "BLOCKED_MISSING_IDEMPOTENCY_CONTRACT",
                "action": primary,
            }

        decision = self._reserve(row, action)
        state = str(decision.get("status") or "")
        if state in {"EXECUTED", "REJECTED", "FAILED", "EXPIRED"}:
            return {"status": f"DUPLICATE_{state}", "decision": decision}

        if state == "EXECUTION_PENDING":
            completed = self._complete_from_order(
                decision, self._database_order(decision_id)
            )
            if completed:
                return {"status": completed["status"], "decision": completed}

        risk_result: Dict[str, Any] = {}
        approval_id = _risk_approval_id(decision_id)
        if state == "PROPOSED":
            risk_result = self._risk_gate(row)
            if risk_result.get("approved") is not True:
                rejected = self._transition(
                    decision_id,
                    "PROPOSED",
                    "REJECTED",
                    error=str(risk_result.get("reason") or "Risk_Agent rejected decision"),
                    metadata={"risk_result": risk_result},
                )
                return {"status": "REJECTED", "decision": rejected}
            approval_id = self._ensure_risk_approval(
                row=row,
                action=action,
                decision_id=decision_id,
                risk_result=risk_result,
            )
            decision = self._transition(
                decision_id,
                "PROPOSED",
                "RISK_APPROVED",
                metadata={
                    "risk_approval_id": approval_id,
                    "risk_result": risk_result,
                },
            )
            state = "RISK_APPROVED"

        if state == "RISK_APPROVED":
            decision = self._transition(
                decision_id,
                "RISK_APPROVED",
                "EXECUTION_PENDING",
                metadata={"risk_approval_id": approval_id},
            )
            state = "EXECUTION_PENDING"

        existing_order = self._database_order(decision_id)
        completed = self._complete_from_order(decision, existing_order)
        if completed:
            return {"status": completed["status"], "decision": completed}
        if existing_order:
            return {
                "status": "EXECUTION_PENDING",
                "decision": decision,
                "order": existing_order,
            }

        order_payload = _order_payload(
            row=row,
            action=action,
            decision_id=decision_id,
            risk_approval_id=approval_id,
            account_id=self.account_id,
            correlation_id=self.correlation_id,
        )
        try:
            response = self._request(
                "execution",
                "POST",
                "/execute",
                order_payload,
                extra_headers={"Idempotency-Key": decision_id},
            )
        except GatewayTimeout:
            return {
                "status": "EXECUTION_PENDING",
                "decision": decision,
                "retry_safe": True,
            }
        except GatewayError as exc:
            if exc.status_code is not None and exc.status_code < 500:
                failed = self._transition(
                    decision_id,
                    "EXECUTION_PENDING",
                    "FAILED",
                    error=str(exc),
                )
                return {"status": "FAILED", "decision": failed}
            return {
                "status": "EXECUTION_PENDING",
                "decision": decision,
                "retry_safe": True,
            }

        response_data = _unwrap(response) or {}
        order = response_data.get("order") if isinstance(response_data, dict) else None
        completed = self._complete_from_order(decision, order)
        if completed:
            return {"status": completed["status"], "decision": completed, "order": order}
        return {
            "status": "EXECUTION_PENDING",
            "decision": decision,
            "order": order,
            "retry_safe": True,
        }


def orchestrate_report(
    report: Dict[str, Any],
    orchestrator: ProfitDecisionOrchestrator,
) -> Dict[str, Any]:
    results = []
    for row in report.get("reviewed_positions") or []:
        result = orchestrator.orchestrate(row)
        row["profit_orchestration"] = result
        results.append(result)
    summary = report.setdefault("summary", {})
    summary["profit_decisions_orchestrated"] = len(results)
    summary["profit_decisions_executed"] = sum(
        result.get("status") == "EXECUTED" for result in results
    )
    summary["profit_decisions_pending"] = sum(
        result.get("status") == "EXECUTION_PENDING" for result in results
    )
    summary["profit_decisions_blocked_or_rejected"] = sum(
        str(result.get("status") or "").startswith(("BLOCKED", "REJECTED", "FAILED"))
        for result in results
    )
    return report


def correlation_id_for_report(report: Dict[str, Any]) -> str:
    generated = str(report.get("generated_at") or datetime.now(timezone.utc).isoformat())
    bucket = str(report.get("bucket") or "unassigned")
    digest = hashlib.sha256(f"{bucket}:{generated}".encode("utf-8")).hexdigest()[:20]
    return f"profit-review-{digest}"


def executable_rows(report: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    return (
        row
        for row in report.get("reviewed_positions") or []
        if str((row.get("profit_plan") or {}).get("primary_action") or "").lower()
        in EXIT_ACTIONS
    )


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run idempotent Manager-owned profit decision orchestration."
    )
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"),
    )
    parser.add_argument(
        "--database-api-key",
        default=os.getenv("DATABASE_AGENT_API_KEY"),
    )
    parser.add_argument(
        "--risk-url",
        default=os.getenv("RISK_AGENT_URL", "http://localhost:8007"),
    )
    parser.add_argument(
        "--execution-url",
        default=os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006"),
    )
    parser.add_argument(
        "--execution-api-key",
        default=os.getenv("EXECUTION_API_KEY") or os.getenv("EXECUTION_AGENT_API_KEY"),
    )
    parser.add_argument(
        "--trading-mode",
        default=os.getenv("TRADING_MODE", "PAPER"),
    )
    parser.add_argument(
        "--correlation-id",
        default=os.getenv("CORRELATION_ID"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not _env_bool("PROFIT_DECISION_EXECUTION_ENABLED", False):
        raise SystemExit(
            "PROFIT_DECISION_EXECUTION_ENABLED=true is required for orchestration"
        )
    report = json.loads(args.input_json.read_text(encoding="utf-8"))
    correlation_id = args.correlation_id or correlation_id_for_report(report)
    gateway = HttpGateway(
        {
            "database": ServiceConfig(args.database_url, args.database_api_key),
            "risk": ServiceConfig(args.risk_url),
            "execution": ServiceConfig(args.execution_url, args.execution_api_key),
        }
    )
    orchestrator = ProfitDecisionOrchestrator(
        gateway,
        account_id=args.account_id,
        correlation_id=correlation_id,
        trading_mode=args.trading_mode,
        allow_exit_all=_env_bool("PROFIT_AUTO_EXIT_ALL_ENABLED", False),
    )
    output = orchestrate_report(report, orchestrator)
    output.setdefault("metadata", {})["profit_correlation_id"] = correlation_id
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(output.get("summary") or {}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
