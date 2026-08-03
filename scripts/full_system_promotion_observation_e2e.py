from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

from app import config as manager_config
from app.services.backtest_execution_gate import filter_candidates_with_backtest_gate
from app.services.promotion_paper_observer import observe_promotion_gate_result
from scripts.full_system_promotion_e2e import (
    AsyncDatabaseTransport,
    PromotionLifecycleE2E,
    require,
    unwrap,
)


class ObservationDatabaseTransport(AsyncDatabaseTransport):
    async def get_orders(self, account_id: str, correlation_id: str) -> Any:
        response = await self._get(
            f"/accounts/{urllib.parse.quote(str(account_id), safe='')}/orders",
            correlation_id,
        )
        return unwrap(response)


class RealExecutionTransport:
    def __init__(self, lifecycle: PromotionLifecycleE2E) -> None:
        self.lifecycle = lifecycle

    async def reconcile_broker_state(
        self,
        account_id: str,
        correlation_id: str,
        *,
        push_to_database: Optional[bool] = None,
    ) -> SimpleNamespace:
        push = "true" if push_to_database is not False else "false"
        encoded_account = urllib.parse.quote(str(account_id), safe="")
        response = await asyncio.to_thread(
            self.lifecycle.request,
            "execution",
            "POST",
            f"/broker/reconcile?account_id={encoded_account}&push_to_database={push}",
            payload={},
            correlation_id=correlation_id,
        )
        require(
            response.get("status") == "success",
            f"Execution reconciliation failed: {response}",
        )
        return SimpleNamespace(data=unwrap(response) or {})


class FaultExecutionTransport:
    def __init__(
        self,
        *,
        open_orders: Optional[list[Dict[str, Any]]] = None,
        positions: Optional[list[Dict[str, Any]]] = None,
        ok: bool = True,
    ) -> None:
        self.open_orders = open_orders or []
        self.positions = positions or []
        self.ok = ok

    async def reconcile_broker_state(
        self,
        account_id: str,
        correlation_id: str,
        *,
        push_to_database: Optional[bool] = None,
    ) -> SimpleNamespace:
        del account_id, correlation_id, push_to_database
        return SimpleNamespace(
            data={
                "ok": self.ok,
                "reconciled_at": datetime.now(timezone.utc).isoformat(),
                "broker_state": {
                    "open_orders": self.open_orders,
                    "positions": self.positions,
                },
            }
        )


class PromotionObservationE2E:
    def __init__(self, lifecycle: PromotionLifecycleE2E, output_path: Path) -> None:
        self.lifecycle = lifecycle
        self.output_path = output_path
        self.database = ObservationDatabaseTransport(lifecycle.gateway)
        self.real_execution = RealExecutionTransport(lifecycle)
        self.report: Dict[str, Any] = {
            "status": "running",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scenarios": {},
        }

    def seed_robust(
        self,
        *,
        scenario: str,
        strategy_id: str,
        fingerprint_character: str,
    ) -> Dict[str, Any]:
        run_id = f"promotion-observation-{scenario}-run"
        fingerprint = fingerprint_character * 64
        self.lifecycle.correlation_id = f"promotion-observation-{scenario}-publish"
        self.lifecycle.seed_run(
            run_id=run_id,
            strategy_id=strategy_id,
            fingerprint=fingerprint,
        )
        robust = self.lifecycle.backtest_advance(
            run_id=run_id,
            strategy_id=strategy_id,
            fingerprint=fingerprint,
        )
        require(robust.get("state") == "ROBUSTNESS_PASSED", str(robust))
        require(robust.get("version") == 4, str(robust))
        return robust

    async def manager_observe(
        self,
        *,
        strategy_id: str,
        correlation_id: str,
        execution_client: Any,
        emergency_halt: bool = False,
    ) -> Dict[str, Any]:
        previous_token = os.environ.get("BACKTEST_PROMOTION_APPROVAL_TOKEN")
        previous_halt = manager_config.MANAGER_EMERGENCY_HALT
        os.environ["BACKTEST_PROMOTION_APPROVAL_TOKEN"] = (
            self.lifecycle.approval_token
        )
        manager_config.MANAGER_EMERGENCY_HALT = emergency_halt
        try:
            return await filter_candidates_with_backtest_gate(
                db_client=self.database,
                selected_positions=[
                    {
                        "account_id": "1",
                        "symbol": "AAPL",
                        "quantity": 1,
                    }
                ],
                position_analysis_payloads=[
                    {
                        "symbol": "AAPL",
                        "strategy_id": strategy_id,
                        "selected_strategy_id": strategy_id,
                    }
                ],
                correlation_id=correlation_id,
                required=True,
                skill_id="hourly-sma-crossover",
                strategy_id=strategy_id,
                strategy_ids=[strategy_id],
                timeframe="1d",
                max_age_hours=26,
                promotion_authority_required=True,
                paper_observation_required=True,
                account_id="1",
                auto_approve=True,
                execution_client=execution_client,
            )
        finally:
            manager_config.MANAGER_EMERGENCY_HALT = previous_halt
            if previous_token is None:
                os.environ.pop("BACKTEST_PROMOTION_APPROVAL_TOKEN", None)
            else:
                os.environ["BACKTEST_PROMOTION_APPROVAL_TOKEN"] = previous_token

    def promotion(self, promotion_id: str) -> Dict[str, Any]:
        return self.lifecycle.promotion(promotion_id)

    def observations(self, promotion_id: str) -> list[Dict[str, Any]]:
        encoded = urllib.parse.quote(promotion_id, safe="")
        response = self.lifecycle.request(
            "database",
            "GET",
            f"/backtests/promotion-observations/{encoded}",
            correlation_id="promotion-observation-ledger-read",
        )
        records = unwrap(response) or []
        require(isinstance(records, list), f"invalid observation ledger: {response}")
        return records

    def create_expiring_approved(
        self,
        *,
        strategy_id: str,
    ) -> tuple[Dict[str, Any], datetime]:
        run_id = "promotion-observation-expiry-run"
        fingerprint = "f" * 64
        correlation_id = "promotion-observation-expiry-publish"
        self.lifecycle.correlation_id = correlation_id
        self.lifecycle.seed_run(
            run_id=run_id,
            strategy_id=strategy_id,
            fingerprint=fingerprint,
        )
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=3)
        create_payload = {
            "account_id": "1",
            "run_id": run_id,
            "skill_id": "hourly-sma-crossover",
            "strategy_id": strategy_id,
            "symbol": "AAPL",
            "timeframe": "1d",
            "dataset_fingerprint": fingerprint,
            "engine_version": "backtest-agent-0.7.0",
            "validation_profile": "nested_walk_forward_v2",
            "evidence_version": 1,
            "expires_at": expires_at.isoformat(),
            "reason_code": "e2e_expiry_published",
            "reason": "Short-lived paper promotion for expiry race verification",
            "correlation_id": correlation_id,
            "metadata": {"source": "promotion-observation-e2e"},
        }
        created = unwrap(
            self.lifecycle.request(
                "database",
                "POST",
                "/backtests/promotions",
                payload=create_payload,
                correlation_id=correlation_id,
            )
        ) or {}
        require(created.get("state") == "GENERATED", str(created))

        current = created
        transitions = (
            ("VALIDATED", "e2e_validated"),
            ("OOS_PASSED", "e2e_oos_passed"),
            ("ROBUSTNESS_PASSED", "e2e_robustness_passed"),
            ("APPROVED_FOR_PAPER", "e2e_approved_for_paper"),
        )
        for next_state, reason_code in transitions:
            encoded = urllib.parse.quote(str(current["promotion_id"]), safe="")
            payload = {
                "expected_state": current["state"],
                "expected_version": current["version"],
                "next_state": next_state,
                "reason_code": reason_code,
                "reason": f"E2E transition to {next_state}",
                "evidence_run_id": run_id,
                "correlation_id": correlation_id,
                "evidence_version": current["evidence_version"],
                "approver": "manager-observation-e2e",
                "metadata": {"source": "promotion-observation-e2e"},
            }
            headers = (
                {"X-PROMOTION-APPROVAL-KEY": self.lifecycle.approval_token}
                if next_state == "APPROVED_FOR_PAPER"
                else None
            )
            current = unwrap(
                self.lifecycle.request(
                    "database",
                    "POST",
                    f"/backtests/promotions/{encoded}/transition",
                    payload=payload,
                    correlation_id=correlation_id,
                    extra_headers=headers,
                )
            ) or {}
            require(current.get("state") == next_state, str(current))
        return current, expires_at

    async def run_async(self) -> None:
        original_mode = manager_config.TRADING_MODE
        original_live = manager_config.ALLOW_LIVE_TRADING
        manager_config.TRADING_MODE = "PAPER"
        manager_config.ALLOW_LIVE_TRADING = False
        try:
            await self._healthy_replay_and_heartbeat()
            await self._reconciliation_mismatch()
            await self._emergency_halt()
            await self._drawdown_revoke()
            await self._expiry_race()
        finally:
            manager_config.TRADING_MODE = original_mode
            manager_config.ALLOW_LIVE_TRADING = original_live

    async def _healthy_replay_and_heartbeat(self) -> None:
        strategy_id = "promotion-observation-healthy-v1"
        robust = self.seed_robust(
            scenario="healthy",
            strategy_id=strategy_id,
            fingerprint_character="1",
        )
        correlation_id = "promotion-observation-healthy-cycle"
        first = await self.manager_observe(
            strategy_id=strategy_id,
            correlation_id=correlation_id,
            execution_client=self.real_execution,
        )
        require(first["summary"]["allowed_count"] == 1, str(first))
        first_observation = first["decisions"][0]["paper_observation"]
        require(first_observation["action"] == "START_OBSERVING", str(first))
        require(first_observation["to_state"] == "PAPER_OBSERVING", str(first))
        require(first_observation["to_version"] == 6, str(first))

        replay = await self.manager_observe(
            strategy_id=strategy_id,
            correlation_id=correlation_id,
            execution_client=self.real_execution,
        )
        replay_observation = replay["decisions"][0]["paper_observation"]
        require(replay["summary"]["allowed_count"] == 1, str(replay))
        require(
            replay_observation["observation_id"]
            == first_observation["observation_id"],
            "same cycle did not replay the same observation",
        )
        require(
            self.promotion(robust["promotion_id"])["version"] == 6,
            "idempotent observation retry incremented promotion version",
        )
        require(
            len(self.observations(robust["promotion_id"])) == 1,
            "idempotent retry created duplicate observation ledger rows",
        )

        heartbeat = await self.manager_observe(
            strategy_id=strategy_id,
            correlation_id="promotion-observation-healthy-heartbeat",
            execution_client=self.real_execution,
        )
        heartbeat_observation = heartbeat["decisions"][0]["paper_observation"]
        require(heartbeat["summary"]["allowed_count"] == 1, str(heartbeat))
        require(heartbeat_observation["action"] == "HEARTBEAT", str(heartbeat))
        require(heartbeat_observation["to_version"] == 7, str(heartbeat))
        ledger = self.observations(robust["promotion_id"])
        require(len(ledger) == 2, str(ledger))
        require(
            {row.get("correlation_id") for row in ledger}
            == {
                correlation_id,
                "promotion-observation-healthy-heartbeat",
            },
            f"observation correlation IDs were not preserved: {ledger}",
        )
        self.report["scenarios"]["healthy_replay_heartbeat"] = {
            "promotion": self.promotion(robust["promotion_id"]),
            "first": first,
            "replay": replay,
            "heartbeat": heartbeat,
            "ledger": ledger,
        }

    async def _reconciliation_mismatch(self) -> None:
        strategy_id = "promotion-observation-mismatch-v1"
        robust = self.seed_robust(
            scenario="mismatch",
            strategy_id=strategy_id,
            fingerprint_character="2",
        )
        mismatch = await self.manager_observe(
            strategy_id=strategy_id,
            correlation_id="promotion-observation-mismatch-cycle",
            execution_client=FaultExecutionTransport(
                open_orders=[
                    {
                        "symbol": "AAPL",
                        "status": "open",
                        "order_id": "broker-only-order",
                    }
                ]
            ),
        )
        require(mismatch["summary"]["allowed_count"] == 0, str(mismatch))
        require(
            self.promotion(robust["promotion_id"])["state"] == "REVOKED",
            str(mismatch),
        )
        require(
            "paper_observation_reconciliation_failed"
            in mismatch["decisions"][0]["rejection_codes"],
            str(mismatch),
        )
        self.report["scenarios"]["reconciliation_mismatch"] = mismatch

    async def _emergency_halt(self) -> None:
        strategy_id = "promotion-observation-halt-v1"
        robust = self.seed_robust(
            scenario="halt",
            strategy_id=strategy_id,
            fingerprint_character="3",
        )
        halted = await self.manager_observe(
            strategy_id=strategy_id,
            correlation_id="promotion-observation-halt-cycle",
            execution_client=FaultExecutionTransport(),
            emergency_halt=True,
        )
        require(halted["summary"]["allowed_count"] == 0, str(halted))
        promotion = self.promotion(robust["promotion_id"])
        require(promotion["state"] == "REVOKED", str(promotion))
        require(promotion["reason_code"] == "emergency_halt", str(promotion))
        self.report["scenarios"]["emergency_halt"] = halted

    async def _drawdown_revoke(self) -> None:
        strategy_id = "promotion-observation-drawdown-v1"
        robust = self.seed_robust(
            scenario="drawdown",
            strategy_id=strategy_id,
            fingerprint_character="4",
        )
        drawdown = await self.manager_observe(
            strategy_id=strategy_id,
            correlation_id="promotion-observation-drawdown-cycle",
            execution_client=FaultExecutionTransport(
                positions=[
                    {
                        "symbol": "AAPL",
                        "unrealized_pl": "-20",
                        "cost_basis": "100",
                    }
                ]
            ),
        )
        require(drawdown["summary"]["allowed_count"] == 0, str(drawdown))
        promotion = self.promotion(robust["promotion_id"])
        require(promotion["state"] == "REVOKED", str(promotion))
        require(
            promotion["reason_code"] == "paper_drawdown_exceeded",
            str(promotion),
        )
        self.report["scenarios"]["paper_drawdown"] = drawdown

    async def _expiry_race(self) -> None:
        strategy_id = "promotion-observation-expiry-v1"
        approved, expires_at = self.create_expiring_approved(
            strategy_id=strategy_id
        )
        delay = max(
            0.0,
            (expires_at - datetime.now(timezone.utc)).total_seconds() + 0.25,
        )
        time.sleep(delay)
        gate_result = {
            "status": "required",
            "required": True,
            "account_id": "1",
            "selected_positions": [{"symbol": "AAPL", "quantity": 1}],
            "position_analysis_payloads": [
                {
                    "symbol": "AAPL",
                    "strategy_id": strategy_id,
                    "selected_strategy_id": strategy_id,
                }
            ],
            "decisions": [
                {
                    "symbol": "AAPL",
                    "allowed": True,
                    "rejection_codes": [],
                    "account_id": "1",
                    "strategy_id": strategy_id,
                    "selected_strategy_id": strategy_id,
                    "promotion_id": approved["promotion_id"],
                    "promotion_state": "APPROVED_FOR_PAPER",
                    "promotion_version": approved["version"],
                    "requires_risk_approval": True,
                    "broker_boundary": "execution-agent-only",
                }
            ],
            "rejected": [],
            "summary": {
                "candidate_count": 1,
                "allowed_count": 1,
                "rejected_count": 0,
            },
        }
        previous_token = os.environ.get("BACKTEST_PROMOTION_APPROVAL_TOKEN")
        os.environ["BACKTEST_PROMOTION_APPROVAL_TOKEN"] = (
            self.lifecycle.approval_token
        )
        try:
            expired = await observe_promotion_gate_result(
                db_client=self.database,
                gate_result=gate_result,
                account_id="1",
                correlation_id="promotion-observation-expiry-cycle",
                execution_client=FaultExecutionTransport(),
            )
        finally:
            if previous_token is None:
                os.environ.pop("BACKTEST_PROMOTION_APPROVAL_TOKEN", None)
            else:
                os.environ["BACKTEST_PROMOTION_APPROVAL_TOKEN"] = previous_token
        require(expired["summary"]["allowed_count"] == 0, str(expired))
        promotion = self.promotion(approved["promotion_id"])
        require(promotion["state"] == "EXPIRED", str(promotion))
        require(promotion["reason_code"] == "promotion_expired", str(promotion))
        self.report["scenarios"]["expiry_race"] = expired

    def run(self) -> None:
        asyncio.run(self.run_async())
        self.report.update(
            {
                "status": "success",
                "finished_at": datetime.now(timezone.utc).isoformat(),
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
        output_path=Path("/tmp/unused-promotion-lifecycle.json"),
    )
    runner = PromotionObservationE2E(
        lifecycle=lifecycle,
        output_path=args.output_json.resolve(),
    )
    try:
        runner.run()
    except Exception as exc:
        runner.report.update(
            {
                "status": "failed",
                "error": str(exc),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        runner.output_path.parent.mkdir(parents=True, exist_ok=True)
        runner.output_path.write_text(
            json.dumps(runner.report, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    main()
