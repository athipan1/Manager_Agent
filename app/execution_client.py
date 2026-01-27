import json
from .resilient_client import ResilientAgentClient, AgentUnavailable
from .models import CreateOrderRequest, CreateOrderResponse
from . import config
from .logger import report_logger


class ExecutionAgentClient(ResilientAgentClient):
    """
    A client for interacting with the Execution Agent.
    """

    def __init__(self):
        headers = {"X-API-KEY": config.EXECUTION_API_KEY}
        super().__init__(
            base_url=config.EXECUTION_AGENT_URL,
            headers=headers
        )

    async def create_order(
        self,
        order_details: CreateOrderRequest,
        correlation_id: str,
    ) -> CreateOrderResponse | dict:
        """
        Submits a new trade order to the Execution Agent
        via POST /execute (Execution Agent contract).

        Args:
            order_details: The Pydantic model containing the order details.
            correlation_id: A unique identifier for tracing the request.

        Returns:
            A CreateOrderResponse object on success,
            or a dictionary with an error message on failure.
        """

        # ✅ FIX: Must match Execution_Agent main.py
        endpoint = "/execute"

        try:
            # Serialize payload (Decimal-safe)
            payload = order_details.model_dump(mode="json")
            idempotency_key = order_details.client_order_id

            report_logger.info(
                f"Sending order to Execution Agent: {payload}, "
                f"correlation_id={correlation_id}"
            )

            response_data = await self._post(
                endpoint=endpoint,
                correlation_id=correlation_id,
                json_data=payload,
                extra_headers={
                    "Idempotency-Key": idempotency_key
                },
            )

            return CreateOrderResponse.model_validate(response_data)

        except AgentUnavailable as e:
            report_logger.error(
                f"Execution Agent is unavailable: {e}, "
                f"correlation_id={correlation_id}"
            )
            return {
                "status": "error",
                "reason": "Execution Agent unavailable",
            }

        except Exception as e:
            report_logger.exception(
                "Unexpected error while creating order "
                f"(correlation_id={correlation_id})"
            )
            return {
                "status": "error",
                "reason": f"Unexpected error: {e}",
            }