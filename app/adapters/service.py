from typing import Dict, Any, Optional
from pydantic import ValidationError
import logging

from app.models import CanonicalAgentResponse, CanonicalAgentData
from .standard_models import StandardAgentResponse
from .legacy_models import LegacyTechnicalAgentResponse, LegacyFundamentalAgentResponse

# It's good practice to have a dedicated logger for this service
logger = logging.getLogger(__name__)


def _normalize_from_standard(
    raw_data: Dict[str, Any]
) -> Optional[CanonicalAgentResponse]:
    """Normalizes a response that conforms to the StandardAgentResponse schema."""
    try:
        parsed = StandardAgentResponse(**raw_data)
        return CanonicalAgentResponse(
            agent_type=parsed.agent_type,
            version=parsed.version,
            data=CanonicalAgentData(**parsed.data.model_dump()),
            raw_metadata=raw_data,
        )
    except ValidationError as e:
        logger.warning(f"Validation failed for standard response: {e}")
        return None


def _normalize_from_legacy_technical(
    raw_data: Dict[str, Any]
) -> Optional[CanonicalAgentResponse]:
    """Normalizes a response from a legacy technical agent."""
    try:
        parsed = LegacyTechnicalAgentResponse(**raw_data)
        # Create the canonical data model, adding extra legacy fields
        canonical_data = CanonicalAgentData(
            action=parsed.data.action,
            confidence_score=parsed.data.confidence_score,
            current_price=parsed.data.current_price,
            indicators=parsed.data.indicators,
        )
        return CanonicalAgentResponse(
            agent_type=parsed.agent_type,
            version="1.0-legacy",  # Assign a specific version for clarity
            data=canonical_data,
            raw_metadata=raw_data,
        )
    except ValidationError as e:
        logger.warning(f"Validation failed for legacy technical response: {e}")
        return None


def _normalize_from_legacy_fundamental(
    raw_data: Dict[str, Any]
) -> Optional[CanonicalAgentResponse]:
    """Normalizes a response from a legacy fundamental agent."""
    try:
        parsed = LegacyFundamentalAgentResponse(**raw_data)
        # Create the canonical data model, adding extra legacy fields
        canonical_data = CanonicalAgentData(
            action=parsed.data.action,
            confidence_score=parsed.data.confidence_score,
            analysis_summary=parsed.data.analysis_summary,
            metrics=parsed.data.metrics,
        )
        return CanonicalAgentResponse(
            agent_type=parsed.agent_type,
            version="1.0-legacy",
            data=canonical_data,
            raw_metadata=raw_data,
        )
    except ValidationError as e:
        logger.warning(f"Validation failed for legacy fundamental response: {e}")
        return None


def normalize_response(raw_data: Dict[str, Any]) -> Optional[CanonicalAgentResponse]:
    """
    Acts as a factory to route and normalize an agent's response.

    It first checks for a versioned, standard schema. If that fails, it tries
    to match against known legacy schemas.
    """
    if not isinstance(raw_data, dict):
        logger.error("Invalid response format: not a dictionary.")
        return None

    # 1. Try to parse as a standard, versioned response first.
    if "version" in raw_data and "agent_type" in raw_data:
        normalized = _normalize_from_standard(raw_data)
        if normalized:
            return normalized

    # 2. If standard parsing fails or keys are missing, try legacy fallbacks.
    agent_type = raw_data.get("agent_type")
    if agent_type == "technical":
        logger.info("Attempting fallback normalization for legacy technical agent.")
        return _normalize_from_legacy_technical(raw_data)

    elif agent_type == "fundamental":
        logger.info("Attempting fallback normalization for legacy fundamental agent.")
        return _normalize_from_legacy_fundamental(raw_data)

    # 3. If no known type matches, log a warning and return None.
    logger.warning(
        f"Unable to normalize response for agent type '{agent_type}'. "
        "No matching standard or legacy schema found."
    )
    return None
