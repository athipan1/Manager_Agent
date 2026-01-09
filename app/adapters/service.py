from typing import Dict, Any, Optional
from pydantic import ValidationError
import logging

from app.models import CanonicalAgentResponse, CanonicalAgentData
from .standard_models import StandardAgentResponse

logger = logging.getLogger(__name__)

def _normalize_from_standard(
    raw_data: Dict[str, Any]
) -> Optional[CanonicalAgentResponse]:
    """Normalizes a response that conforms to the StandardAgentResponse schema."""
    try:
        parsed = StandardAgentResponse(**raw_data)
        # Check if there is an error
        if parsed.status == "error" and parsed.error:
            # If there is an error, create a CanonicalAgentResponse with error information
            return CanonicalAgentResponse(
                agent_type=parsed.agent_type,
                version=parsed.version,
                data=CanonicalAgentData(
                    action="hold", # Default action on error
                    confidence_score=0.0, # Default confidence on error
                    reason=parsed.error.get("message", "Unknown error")
                ),
                raw_metadata=raw_data,
                error=parsed.error # Also pass the full error object
            )
        else:
            # If there is no error, create a normal CanonicalAgentResponse
            return CanonicalAgentResponse(
                agent_type=parsed.agent_type,
                version=parsed.version,
                data=CanonicalAgentData(**parsed.data.model_dump()),
                raw_metadata=raw_data,
                error=None
            )
    except ValidationError as e:
        logger.warning(f"Validation failed for standard response: {e}")
        return None

def normalize_response(raw_data: Dict[str, Any]) -> Optional[CanonicalAgentResponse]:
    """
    Acts as a factory to route and normalize an agent's response.
    Assumes all agents now return a StandardAgentResponse.
    """
    if not isinstance(raw_data, dict):
        logger.error("Invalid response format: not a dictionary.")
        return None

    # Attempt to normalize from StandardAgentResponse only
    normalized = _normalize_from_standard(raw_data)
    if normalized:
        return normalized

    logger.warning(
        f"Unable to normalize response. No matching standard schema found or validation failed."
    )
    return None
