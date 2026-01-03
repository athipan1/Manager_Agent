
from typing import Union
from app.models import (
    CanonicalAgentResponse,
    CanonicalAgentData,
    CreateOrderResponse,
    Order,
)

def normalize_database_response(
    db_response: Union[CreateOrderResponse, Order],
) -> CanonicalAgentResponse:
    """
    Normalizes the response from a database operation into the canonical format.
    """
    if isinstance(db_response, CreateOrderResponse):
        action = "hold"  # Creating an order is a neutral action in analysis terms
        confidence = 1.0 if db_response.status == "pending" else 0.0
        data = {"order_id": db_response.order_id, "status": db_response.status}
    elif isinstance(db_response, Order):
        action = db_response.order_type.lower()
        confidence = 1.0 if db_response.status == "executed" else 0.0
        data = db_response.model_dump()
    else:
        # Fallback for unexpected types
        action = "hold"
        confidence = 0.0
        data = {"error": "Unknown database response type"}

    return CanonicalAgentResponse(
        agent_type="database",
        version="1.0",
        data=CanonicalAgentData(
            action=action,
            confidence_score=confidence,
            **data,
        ),
        raw_metadata=data,
    )
