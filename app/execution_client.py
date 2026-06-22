from .resilient_client import ResilientAgentClient, AgentUnavailable
from .contracts import (
    CreateOrderRequest,
    CreateOrderResponse,
    ExecutionEndpoints,
    StandardAgentResponse,
)
from . import config
from .alerts import alert_service
from .logger import report_logger
from .readiness_gate import ReadinessGateError, check_symbol_readiness, readiness_required


def _is_rejected_status(status) -> bool:
    return str(status).lower() in {"failed", "rejected", "cancelled", "error"}


def _reconciliation_ok(response: StandardAgentResponse) -> bool:
    data = response.data or {}
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    if not isinstance(data, dict):
        return False
    return bool(data.get("ok", False))


class ExecutionAgentClient(ResilientAgentClient):
    """
    A client for interacting with the Execution Agent.
    """

    def __init__(self):
        headers = {"X-API-KEY": config.EXECUTION_API_KEY}
        super().__init__(base_url=config.EXECUTION_AGENT_URL, headers=headers)

    async def health(self, correlation_id: str) -> StandardAgentResponse:
        response_data = await self._get(ExecutionEndpoints.HEALTH, correlation_id)
        return self.validate_standard_response(response_data)

    async def broker_state(self, account_id: str | int, correlation_id: str) -> StandardAgentResponse:
        response_data = await self._get(f"{ExecutionEndpoints.BROKER_STATE}?account_id={account_id}", correlation_id)
        return self.validate_standard_response(response_data)

    async def reconcile_broker_state(self, account_id: str | int, correlation_id: str, *, push_to_database: bool | None = None) -> StandardAgentResponse:
        should_push = config.BROKER_RECONCILE_PUSH_TO_DATABASE if push_to_database is None else push_to_database
        endpoint = f"{ExecutionEndpoints.BROKER_RECONCILE}?account_id={account_id}&push_to_database={'true' if should_push else 'false'}"
        response_data = await self._post(url=endpoint, correlation_id=correlation_id, json_data={})
        return self.validate_standard_response(response_data)

    async def _reconcile_before_execution(self, account_id: str | int, correlation_id: str, symbol: str) -> StandardAgentResponse | None:
        if not config.BROKER_RECONCILE_BEFORE_EXECUTION:
            return None
        try:
            reconciliation = await self.reconcile_broker_state(account_id, correlation_id)
            report_logger.info(f"Broker reconciliation before execution for {symbol}: {reconciliation}, correlation_id={correlation_id}")
            if config.BROKER_RECONCILE_REQUIRED and not _reconciliation_ok(reconciliation):
                reason = "Broker reconciliation failed before execution."
                alert_service.record_approval_reject(correlation_id=correlation_id, symbol=symbol, reason=reason, metadata={"source": "broker_reconciliation", "reconciliation": reconciliation.model_dump(mode="json")})
                raise RuntimeError(reason)
            return reconciliation
        except Exception as exc:
            report_logger.error(f"Broker reconciliation failed before execution for {symbol}: {exc}, correlation_id={correlation_id}")
            if config.BROKER_RECONCILE_REQUIRED:
                raise
            return None

    async def create_order(self, order_details: CreateOrderRequest, correlation_id: str) -> CreateOrderResponse:
        """
        Submits a new order to the Execution Agent after Manager readiness checks
        and an optional broker-state reconciliation.
        """
        endpoint = ExecutionEndpoints.EXECUTE

        try:
            await self._reconcile_before_execution(order_details.account_id, correlation_id, order_details.symbol)

            if readiness_required():
                readiness = await check_symbol_readiness(order_details.symbol, correlation_id)
                report_logger.info(f"Manager readiness check for {order_details.symbol}: {readiness}, correlation_id={correlation_id}")
                if not readiness.get("approved"):
                    reason = f"Manager readiness gate rejected execution: {readiness.get('reason')}"
                    alert_service.record_approval_reject(correlation_id=correlation_id, symbol=order_details.symbol, reason=reason, metadata={"source": "readiness_gate", "readiness": readiness})
                    return CreateOrderResponse(order_id="readiness-gate", client_order_id=order_details.client_order_id, status="failed", reason=reason)

            payload = order_details.model_dump(mode="json")
            if "client_order_id" in payload and "trade_id" not in payload:
                payload["trade_id"] = payload.pop("client_order_id")

            idempotency_key = order_details.client_order_id
            report_logger.info(f"Sending order to Execution Agent: {payload}, correlation_id={correlation_id}")

            response_data = await self._post(url=endpoint, correlation_id=correlation_id, json_data=payload, extra_headers={"Idempotency-Key": idempotency_key})
            standard_resp = self.validate_standard_response(response_data)
            response = CreateOrderResponse.model_validate(standard_resp.data)
            if _is_rejected_status(response.status):
                alert_service.record_approval_reject(correlation_id=correlation_id, symbol=order_details.symbol, reason=response.reason or f"Execution status {response.status}", metadata={"source": "execution_agent", "order_id": response.order_id})
            return response

        except ReadinessGateError as e:
            report_logger.error(f"Readiness gate failed for {order_details.symbol}: {e}, correlation_id={correlation_id}")
            alert_service.record_approval_reject(correlation_id=correlation_id, symbol=order_details.symbol, reason=str(e), metadata={"source": "readiness_gate_exception"})
            return CreateOrderResponse(order_id="readiness-gate", client_order_id=order_details.client_order_id, status="failed", reason=str(e))

        except AgentUnavailable as e:
            report_logger.error(f"Execution Agent is unavailable: {e}, correlation_id={correlation_id}")
            raise

        except Exception as exc:
            if config.BROKER_RECONCILE_REQUIRED:
                reason = str(exc)
                alert_service.record_approval_reject(correlation_id=correlation_id, symbol=order_details.symbol, reason=reason, metadata={"source": "execution_client_exception"})
                return CreateOrderResponse(order_id="broker-reconciliation", client_order_id=order_details.client_order_id, status="failed", reason=reason)
            report_logger.exception(f"Unexpected error while creating order (correlation_id={correlation_id})")
            raise
