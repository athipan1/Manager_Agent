from .resilient_client import ResilientAgentClient, AgentUnavailable
from .contracts import (
    CreateOrderRequest,
    CreateOrderResponse,
    ExecutionEndpoints,
    StandardAgentResponse,
)
from . import config
from .logger import report_logger
from .readiness_gate import ReadinessGateError, check_symbol_readiness, readiness_required


class ExecutionAgentClient(ResilientAgentClient):
    """
    A client for interacting with the Execution Agent.
    """

    def __init__(self):
        headers = {"X-API-KEY": config.EXECUTION_API_KEY}
        super().__init__(base_url=config.EXECUTION_AGENT_URL, headers=headers)

    async def create_order(
        self,
        order_details: CreateOrderRequest,
        correlation_id: str,
    ) -> CreateOrderResponse:
        """
        Submits a new order to the Execution Agent after Manager readiness checks.
        """
        endpoint = ExecutionEndpoints.EXECUTE

        try:
            if readiness_required():
                readiness = await check_symbol_readiness(order_details.symbol, correlation_id)
                report_logger.info(
                    f"Manager readiness check for {order_details.symbol}: {readiness}, "
                    f"correlation_id={correlation_id}"
                )
                if not readiness.get("approved"):
                    return CreateOrderResponse(
                        order_id="readiness-gate",
                        client_order_id=order_details.client_order_id,
                        status="failed",
                        reason=f"Manager readiness gate rejected execution: {readiness.get('reason')}",
                    )

            payload = order_details.model_dump(mode="json")
            if "client_order_id" in payload and "trade_id" not in payload:
                payload["trade_id"] = payload.pop("client_order_id")

            idempotency_key = order_details.client_order_id

            report_logger.info(
                f"Sending order to Execution Agent: {payload}, "
                f"correlation_id={correlation_id}"
            )

            response_data = await self._post(
                url=endpoint,
                correlation_id=correlation_id,
                json_data=payload,
                extra_headers={"Idempotency-Key": idempotency_key},
            )

            standard_resp = self.validate_standard_response(response_data)
            return CreateOrderResponse.model_validate(standard_resp.data)

        except ReadinessGateError as e:
            report_logger.error(
                f"Readiness gate failed for {order_details.symbol}: {e}, "
                f"correlation_id={correlation_id}"
            )
            return CreateOrderResponse(
                order_id="readiness-gate",
                client_order_id=order_details.client_order_id,
                status="failed",
                reason=str(e),
            )

        except AgentUnavailable as e:
            report_logger.error(
                f"Execution Agent is unavailable: {e}, "
                f"correlation_id={correlation_id}"
            )
            raise

        except Exception:
            report_logger.exception(
                "Unexpected error while creating order "
                f"(correlation_id={correlation_id})"
            )
            raise
