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

def _normalize_from_scanner(raw_data: Dict[str, Any]) -> Optional[CanonicalAgentResponse]:
    """Special normalizer for Scanner Agent which uses a different schema."""
    if raw_data.get("agent") != "Scanner_Agent":
        return None

    status = "success" if raw_data.get("status") in ["success", "partial_success"] else "error"
    candidates = raw_data.get("data", {}).get("candidates", [])

    # If it's a fundamental scan, candidates have 'grade' and 'thesis'
    # If it's a technical scan, candidates have 'recommendation'

    if not candidates:
        return CanonicalAgentResponse(
            agent_type="scanner",
            version=raw_data.get("version", "1.0.0"),
            data=CanonicalAgentData(action="hold", confidence_score=0.0, reason="No candidates found"),
            raw_metadata=raw_data
        )

    # For multi-asset scanner, normalization to a single CanonicalAgentData is tricky.
    # Here we just take the first candidate as a representative for the "analysis" of that ticker.
    first = candidates[0]
    action = "hold"
    reason = "No recommendation"

    if "recommendation" in first: # Technical scan
        action = "buy" if "buy" in first["recommendation"].lower() else "sell" if "sell" in first["recommendation"].lower() else "hold"
        reason = first["recommendation"]
    elif "grade" in first: # Fundamental scan
        action = "buy" if first["grade"] in ["A", "B"] else "hold"
        reason = first.get("thesis", "Fundamental candidate")

    return CanonicalAgentResponse(
        agent_type="scanner",
        version="1.0.0",
        data=CanonicalAgentData(
            action=action,
            confidence_score=0.7, # Default confidence for scanner candidates
            reason=reason
        ),
        raw_metadata=raw_data
    )

def normalize_response(raw_data: Dict[str, Any]) -> Optional[CanonicalAgentResponse]:
    """
    Acts as a factory to route and normalize an agent's response.
    Assumes all agents now return a StandardAgentResponse, with a fallback for Scanner_Agent.
    """
    if not isinstance(raw_data, dict):
        logger.error("Invalid response format: not a dictionary.")
        return None

    # 1. Try StandardAgentResponse
    normalized = _normalize_from_standard(raw_data)
    if normalized:
        return normalized

    # 2. Try Scanner Agent special normalization
    normalized = _normalize_from_scanner(raw_data)
    if normalized:
        return normalized

    logger.warning(
        f"Unable to normalize response. No matching standard schema found or validation failed."
    )
    return None
