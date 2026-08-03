from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

from app.services.backtest_execution_gate import filter_candidates_with_backtest_gate
from scripts.profit_decision_orchestrator import HttpGateway, ServiceConfig


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


class AsyncDatabaseTransport:
    """Adapt the real Manager promotion gate to the E2E HTTP gateway."""

    def __init__(self, gateway: HttpGateway, correlation_id: str):
        self.gateway = gateway
        self.correlation_id = correlation_id

    async def _get(self, path, correlation_id, **kwargs):
        params = kwargs.get("params") or {}
        query = urllib.parse.urlencode(params)
        target = f"{path}?{query}" if query else path
        return await asyncio.to_thread(
            self.gateway.request,
            "database",
            "GET",
            target,
            correlation_id=correlation_id,
        )

    async def _post(
        self,
        path,
        correlation_id,
        json_data,
        extra_headers=None,
        **kwargs,
    ):
        return await asyncio.to_thread(
            self.gateway.request,
            "database",
            "POST",
            path,
            correlation_id=correlation_id,
            payload=json_data,
            extra_headers=extra_headers,
        )

    @staticmethod
    def validate_standard_response(response_data):
        if response_data.get("status") != "success":
            raise RuntimeError(f"Database operation failed: {response_data}")
        return SimpleNamespace(data=response_data.get("data"))


class PromotionLifecycleE2E:
    def __init__(
        self,
        *,
        database_url: str,
        database_api_key: str,
        risk_url: str,
        execution_url: str,
        execution_api_key: str,
        approval_token: str,
        backtest_repository: Path,
        output_path: Path,
    ) -> None:
        self.gateway = HttpGateway(
            {
                "database": ServiceConfig(database_url, database_api_key),
                "risk": ServiceConfig(risk_url),
                "execution": ServiceConfig(execution_url, execution_api_key),
            },
            timeout=40,
        )
        self.database_url = database_url
        self.database_api_key = database_api_key
        self.approval_token = approval_token
        self.backtest_repository = backtest_repository
        self.output_path = output_path
        self.correlation_id = "promotion-e2e-correlation-001"
        self.report: Dict[str, Any] = {
            "status": "running",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "correlation_id": self.correlation_id,
            "scenarios": [],
        }

    def request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return self.gateway.request(
            service,
            method,
            path,
            correlation_id=correlation_id or self.correlation_id,
            payload=payload,
            extra_headers=extra_headers,
        )

    @staticmethod
    def metadata(strategy_id: str) -> Dict[str, Any]:
        return {
            "dataset_fingerprint": "a" * 64,
            "validation_profile": "nested_walk_forward_v2",
            "walk_forward_validation": {
                "status": "completed",
                "selection_method": "nested_train_select_test_evaluate",
                "passed": True,
                "evaluated_windows": 4,
                "overlapping_test_windows": False,
                "latest_selection_eligible": True,
                "latest_selected_strategy_id": strategy_id,
                "total_kill_switch_events": 0,
                "train_eligible_window_rate": 0.75,
                "profitable_window_rate": 0.75,
                "median_sharpe_ratio": 1.1,
                "median_profit_factor": 1.4,
                "worst_max_drawdown": -0.12,
            },
            "walk_forward_criteria": {"min_windows": 4},
            "promotion_gates": {
                "nested_validation_passed": True,
                "latest_selection_eligible": True,
                "exact_strategy_match": True,
                "independent_test_windows": True,
                "statistical_validation_enabled": True,
            },
            "statistical_criteria": {
                "enabled": True,
                "max_adjusted_p_value": 0.05,
                "min_probabilistic_sharpe_ratio": 0.95,
                "min_deflated_sharpe_probability": 0.90,
                "min_bootstrap_annualized_return": 0.0,
            },
            "statistical_evidence": {
                "status": "completed",
                "passed": True,
                "observation_count": 200,
                "trade_count": 40,
                "adjusted_p_value": 0.01,
                "probabilistic_sharpe_ratio": 0.98,
                "deflated_sharpe_probability": 0.94,
                "bootstrap_annualized_return_lower": 0.02,
                "gates": {
                    "observation_count": True,
                    "trade_count": True,
                    "adjusted_p_value": True,
                    "probabilistic_sharpe_ratio": True,
                    "deflated_sharpe_probability": True,
                    "bootstrap_lower_bound": True,
                },
            },
            "selection_gates": {
                "statistical_adjusted_p_value": True,
                "statistical_probabilistic_sharpe_ratio": True,
                "statistical_deflated_sharpe_probability": True,
                "statistical_bootstrap_lower_bound": True,
            },
            "robustness_validation": {
                "status": "completed",
                "passed": True,
                "scenario_pass_rate": 1.0,
                "catastrophic_loss": False,
                "gates": {
                    "parameter_perturbation": True,
                    "fee_stress": True,
                    "spread_stress": True,
                    "slippage_stress": True,
                    "liquidity_stress": True,
                    "drawdown_stress": True,
                    "minimum_scenario_pass_rate": True,
                    "no_catastrophic_loss": True,
                    "finite_metrics": True,
                },
            },
            "immutable_evidence_snapshot": True,
        }

    def seed_run(self, *, run_id: str, strategy_id: str, fingerprint: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        metadata = self.metadata(strategy_id)
        metadata["dataset_fingerprint"] = fingerprint
        payload = {
            "run_id": run_id,
            "account_id": "1",
            "skill_id": "hourly-sma-crossover",
            "strategy_id": strategy_id,
            "symbol": "AAPL",
            "timeframe": "1d",
            "start_time": (now - timedelta(days=365)).isoformat(),
            "end_time": now.isoformat(),
            "status": "completed",
            "engine_version": "backtest-agent-0.7.0",
            "parameters": {"strategy": "trend_following"},
            "metrics": {"total_trades": 40, "kill_switch_events": 0},
            "source_agent": "backtest-agent",
            "metadata": metadata,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "trades": [],
            "equity_curve": [],
            "skill_result": {
                "result_id": f"result-{run_id}",
                "skill_id": "hourly-sma-crossover",
                "run_id": run_id,
                "passed": True,
                "status": "backtest_passed",
                "total_trades": 40,
                "reasons": [],
                "metadata": {},
                "created_at": now.isoformat(),
            },
        }
        response = self.request("database", "POST", "/backtests/runs", payload=payload)
        require(response.get("status") == "success", f"run seed failed: {response}")
        return unwrap(response) or {}

    def backtest_advance(
        self,
        *,
        run_id: str,
        strategy_id: str,
        fingerprint: str,
    ) -> Dict[str, Any]:
        code = """
import json
import os
from app.database_client import DatabaseAgentClient
from app.promotion_lifecycle import create_and_advance_backtest_promotion

client = DatabaseAgentClient()
record = create_and_advance_backtest_promotion(
    client,
    account_id='1',
    run_id=os.environ['E2E_RUN_ID'],
    skill_id='hourly-sma-crossover',
    strategy_id=os.environ['E2E_STRATEGY_ID'],
    symbol='AAPL',
    timeframe='1d',
    dataset_fingerprint=os.environ['E2E_FINGERPRINT'],
    engine_version='backtest-agent-0.7.0',
    validation_profile='nested_walk_forward_v2',
    correlation_id=os.environ['E2E_CORRELATION_ID'],
)
print(json.dumps(record, sort_keys=True))
"""
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(self.backtest_repository),
                "DATABASE_AGENT_URL": self.database_url,
                "DATABASE_AGENT_API_KEY": self.database_api_key,
                "E2E_RUN_ID": run_id,
                "E2E_STRATEGY_ID": strategy_id,
                "E2E_FINGERPRINT": fingerprint,
                "E2E_CORRELATION_ID": self.correlation_id,
            }
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=self.backtest_repository,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        require(
            completed.returncode == 0,
            f"Backtest lifecycle subprocess failed: {completed.stdout}\n{completed.stderr}",
        )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        require(lines, "Backtest lifecycle subprocess returned no JSON")
        return json.loads(lines[-1])

    async def manager_authorize(self, *, strategy_id: str) -> Dict[str, Any]:
        transport = AsyncDatabaseTransport(self.gateway, self.correlation_id)
        previous = os.environ.get("BACKTEST_PROMOTION_APPROVAL_TOKEN")
        os.environ["BACKTEST_PROMOTION_APPROVAL_TOKEN"] = self.approval_token
        try:
            result = await filter_candidates_with_backtest_gate(
                db_client=transport,
                selected_positions=[
                    {"account_id": "1", "symbol": "AAPL", "quantity": 1}
                ],
                position_analysis_payloads=[{"symbol": "AAPL"}],
                correlation_id=self.correlation_id,
                required=True,
                skill_id="hourly-sma-crossover",
                strategy_id=strategy_id,
                strategy_ids=[strategy_id],
                timeframe="1d",
                max_age_hours=26,
                promotion_authority_required=True,
                account_id="1",
                auto_approve=True,
            )
        finally:
            if previous is None:
                os.environ.pop("BACKTEST_PROMOTION_APPROVAL_TOKEN", None)
            else:
                os.environ["BACKTEST_PROMOTION_APPROVAL_TOKEN"] = previous
        return result

    def risk_approve(self, *, strategy_id: str) -> Dict[str, Any]:
        payload = {
            "symbol": "AAPL",
            "decision": {
                "decision": "candidate_approved",
                "confidence": "high",
                "recommended_strategy": strategy_id,
                "backtest_best_strategy": strategy_id,
                "reason": "approved exact promotion",
            },
            "market_context": {
                "position_size_multiplier": 1.0,
                "risk_budget_multiplier": 1.0,
                "exposure_cap": 0.50,
                "effective_size_multiplier": 1.0,
                "allowed_strategies": [strategy_id],
                "blocked_strategies": [],
                "decision_notes": ["promotion authority verified"],
            },
            "account": {
                "equity": 100000,
                "current_exposure_pct": 0.0,
                "current_symbol_exposure_pct": 0.0,
                "open_orders_exposure_pct": 0.0,
            },
            "requested_position_pct": 0.01,
            "trading_mode": "PAPER",
        }
        response = self.request("risk", "POST", "/risk/manager-gate", payload=payload)
        result = unwrap(response) or {}
        require(result.get("approved") is True, f"Risk rejected promotion: {response}")
        return result

    def create_risk_approval(self, *, risk_result: Dict[str, Any], trade_id: str) -> str:
        approval_id = f"promotion-risk-{trade_id}"
        payload = {
            "approval_id": approval_id,
            "account_id": "1",
            "symbol": "AAPL",
            "side": "buy",
            "approved_quantity": 1,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "metadata": {
                "source": "risk_agent_manager_gate",
                "risk_result": risk_result,
                "correlation_id": self.correlation_id,
                "promotion_authority_verified": True,
            },
        }
        response = self.request("database", "POST", "/risk-approvals", payload=payload)
        approval = unwrap(response) or {}
        require(approval.get("status") == "approved", f"approval seed failed: {response}")
        return approval_id

    def execute(self, *, trade_id: str, approval_id: str) -> Dict[str, Any]:
        payload = {
            "trade_id": trade_id,
            "account_id": "1",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 1,
            "time_in_force": "GTC",
            "strategy_bucket": "unassigned",
            "risk_approval_id": approval_id,
            "final_quantity": 1,
            "metadata": {
                "correlation_id": self.correlation_id,
                "promotion_authority_verified": True,
            },
        }
        return self.request(
            "execution",
            "POST",
            "/execute",
            payload=payload,
            extra_headers={"Idempotency-Key": trade_id},
        )

    def promotion(self, promotion_id: str) -> Dict[str, Any]:
        encoded = urllib.parse.quote(promotion_id, safe="")
        return unwrap(
            self.request(
                "database",
                "GET",
                f"/backtests/promotions/{encoded}",
            )
        ) or {}

    def promotion_history(self, promotion_id: str) -> list[Dict[str, Any]]:
        encoded = urllib.parse.quote(promotion_id, safe="")
        response = self.request(
            "database",
            "GET",
            f"/backtests/promotions/{encoded}/history",
        )
        return unwrap(response) or []

    def run(self) -> None:
        strategy_id = "trend-following-balanced-v1"
        fingerprint = "a" * 64
        run_id = "promotion-e2e-run-001"
        self.seed_run(run_id=run_id, strategy_id=strategy_id, fingerprint=fingerprint)
        robust = self.backtest_advance(
            run_id=run_id,
            strategy_id=strategy_id,
            fingerprint=fingerprint,
        )
        require(robust.get("state") == "ROBUSTNESS_PASSED", str(robust))
        require(robust.get("version") == 4, "Backtest must stop at version 4")

        manager = asyncio.run(self.manager_authorize(strategy_id=strategy_id))
        require(manager["summary"]["allowed_count"] == 1, str(manager))
        decision = manager["decisions"][0]
        require(decision["promotion_state"] == "APPROVED_FOR_PAPER", str(decision))
        require(decision["requires_risk_approval"] is True, str(decision))
        require(decision["broker_boundary"] == "execution-agent-only", str(decision))

        approved = self.promotion(robust["promotion_id"])
        require(approved.get("state") == "APPROVED_FOR_PAPER", str(approved))
        history = self.promotion_history(robust["promotion_id"])
        require(len(history) == 4, f"expected 4 transitions, got {history}")
        require(
            all(row.get("correlation_id") == self.correlation_id for row in history),
            f"promotion history lost correlation ID: {history}",
        )

        risk_result = self.risk_approve(strategy_id=strategy_id)
        trade_id = "promotion-e2e-order-001"
        approval_id = self.create_risk_approval(
            risk_result=risk_result,
            trade_id=trade_id,
        )
        first = self.execute(trade_id=trade_id, approval_id=approval_id)
        second = self.execute(trade_id=trade_id, approval_id=approval_id)
        first_data = unwrap(first) or {}
        second_data = unwrap(second) or {}
        require(
            first_data.get("order_id") == second_data.get("order_id"),
            f"idempotent retry created a duplicate order: {first_data}, {second_data}",
        )
        order = unwrap(
            self.request(
                "database",
                "GET",
                f"/orders/trade/{urllib.parse.quote(trade_id, safe='')}",
            )
        ) or {}
        require(order.get("risk_approval_id") == approval_id, str(order))
        require(
            (order.get("metadata") or {}).get("correlation_id")
            == self.correlation_id,
            f"order lost correlation ID: {order}",
        )
        stored_approval = unwrap(
            self.request(
                "database",
                "GET",
                f"/risk-approvals/{urllib.parse.quote(approval_id, safe='')}",
            )
        ) or {}
        require(
            (stored_approval.get("metadata") or {}).get("correlation_id")
            == self.correlation_id,
            f"risk approval lost correlation ID: {stored_approval}",
        )

        newer_run_id = "promotion-e2e-run-002"
        newer_fingerprint = "b" * 64
        self.seed_run(
            run_id=newer_run_id,
            strategy_id=strategy_id,
            fingerprint=newer_fingerprint,
        )
        newer = self.backtest_advance(
            run_id=newer_run_id,
            strategy_id=strategy_id,
            fingerprint=newer_fingerprint,
        )
        fail_payload = {
            "expected_state": "ROBUSTNESS_PASSED",
            "expected_version": newer["version"],
            "next_state": "FAILED",
            "reason_code": "e2e_newer_evidence_failed",
            "reason": "newer evidence failed after publication",
            "evidence_run_id": newer_run_id,
            "evidence_version": newer["evidence_version"],
            "correlation_id": self.correlation_id,
            "metadata": {"source": "promotion-e2e"},
        }
        failed_response = self.request(
            "database",
            "POST",
            f"/backtests/promotions/{urllib.parse.quote(newer['promotion_id'], safe='')}/transition",
            payload=fail_payload,
        )
        require((unwrap(failed_response) or {}).get("state") == "FAILED", str(failed_response))
        blocked = asyncio.run(self.manager_authorize(strategy_id=strategy_id))
        require(blocked["summary"]["allowed_count"] == 0, str(blocked))
        codes = set(blocked["decisions"][0]["rejection_codes"])
        require(
            "backtest_promotion_terminal_failed" in codes,
            f"newer failed evidence did not block older approval: {blocked}",
        )

        replay = self.backtest_advance(
            run_id=run_id,
            strategy_id=strategy_id,
            fingerprint=fingerprint,
        )
        require(
            replay.get("state") == "APPROVED_FOR_PAPER",
            f"replay mutated downstream authority: {replay}",
        )
        require(
            len(self.promotion_history(robust["promotion_id"])) == 4,
            "Backtest replay created duplicate promotion transitions",
        )

        self.report.update(
            {
                "status": "success",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "promotion": approved,
                "promotion_history": history,
                "manager_decision": decision,
                "risk_result": risk_result,
                "risk_approval": stored_approval,
                "execution_first": first_data,
                "execution_retry": second_data,
                "order": order,
                "newer_failed_promotion": unwrap(failed_response),
                "newer_failed_block": blocked,
            }
        )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(self.report, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--database-api-key", required=True)
    parser.add_argument("--risk-url", required=True)
    parser.add_argument("--execution-url", required=True)
    parser.add_argument("--execution-api-key", required=True)
    parser.add_argument("--approval-token", required=True)
    parser.add_argument("--backtest-repository", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    lifecycle = PromotionLifecycleE2E(
        database_url=args.database_url,
        database_api_key=args.database_api_key,
        risk_url=args.risk_url,
        execution_url=args.execution_url,
        execution_api_key=args.execution_api_key,
        approval_token=args.approval_token,
        backtest_repository=args.backtest_repository.resolve(),
        output_path=args.output_json.resolve(),
    )
    try:
        lifecycle.run()
    except Exception as exc:
        lifecycle.report.update(
            {
                "status": "failed",
                "error": str(exc),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        lifecycle.output_path.parent.mkdir(parents=True, exist_ok=True)
        lifecycle.output_path.write_text(
            json.dumps(lifecycle.report, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    main()
