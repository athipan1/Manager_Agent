from uuid import UUID
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
        super().__init__(base_url=config.EXECUTION_AGENT_URL, headers=headers)

    async def create_order(
        self,
        order_details: CreateOrderRequest,
        correlation_id: str,
    ) -> CreateOrderResponse | dict:
        """
        Submits a new trade order to the Execution Agent.

        Args:
            order_details: The Pydantic model containing the order details.
            correlation_id: A unique identifier for tracing the request.

        Returns:
            A CreateOrderResponse object on success, or a dictionary with an error message on failure.
        """
        endpoint = "/orders"
        try:
            # Pydantic's model_dump is used for serialization, including Decimals
            payload = order_details.model_dump(mode='json')

            report_logger.info(
                f"Sending order to Execution Agent: {payload}, correlation_id={correlation_id}"
            )

            response_data = await self._post(
                endpoint,
                correlation_id,
                json_data=payload,
            )

            return CreateOrderResponse.model_validate(response_data)

        except AgentUnavailable as e:
            report_logger.error(
                f"Execution Agent is unavailable: {e}, correlation_id={correlation_id}"
            )
            return {"status": "error", "reason": "Execution Agent unavailable"}
        except Exception as e:
            report_logger.exception(
                f"An unexpected error occurred while creating order: {e}, "
                f"correlation_id={correlation_id}"
            )
            return {"status": "error", "reason": f"An unexpected error occurred: {e}"}
