from .resilient_client import ResilientAgentClient, AgentUnavailable
from .contracts import (
    CreateOrderRequest,
    CreateOrderResponse,
    ExecutionEndpoints,
    StandardAgentResponse
)
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
    ) -> CreateOrderResponse:
        """
        Submits a new trade order to the Execution Agent.
        """
        endpoint = ExecutionEndpoints.EXECUTE

        try:
            # Serialize payload (Decimal-safe)
            payload = order_details.model_dump(mode="json")
            idempotency_key = order_details.client_order_id

            report_logger.info(
                f"Sending order to Execution Agent: {payload}, "
                f"correlation_id={correlation_id}"
            )

            response_data = await self._post(
                url=endpoint,
                correlation_id=correlation_id,
                json_data=payload,
                extra_headers={
                    "Idempotency-Key": idempotency_key
                },
            )

            standard_resp = self.validate_standard_response(response_data)
            return CreateOrderResponse.model_validate(standard_resp.data)

        except AgentUnavailable as e:
            report_logger.error(
                f"Execution Agent is unavailable: {e}, "
                f"correlation_id={correlation_id}"
            )
            raise

        except Exception as e:
            report_logger.exception(
                "Unexpected error while creating order "
                f"(correlation_id={correlation_id})"
            )
            raise
