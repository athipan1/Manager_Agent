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


# 1. เพิ่มฟังก์ชันสำหรับ Handle Fundamental Agent แบบใหม่โดยเฉพาะ
def _normalize_from_fundamental_v2(
    raw_data: Dict[str, Any]
) -> Optional[CanonicalAgentResponse]:
    """
    Normalizes response specifically for the new Fundamental Agent structure.
    Structure: { "agent": "fundamental_agent", "data": { "analysis": { ... } } }
    """
    try:
        # เจาะเข้าไปเอาข้อมูลในชั้น analysis
        analysis_data = raw_data.get("data", {}).get("analysis", {})

        if not analysis_data:
            raise ValidationError("Missing 'analysis' data block")

        # Map ข้อมูลให้เข้ากับ Canonical Model ของ Manager
        canonical_data = CanonicalAgentData(
            action=analysis_data.get("action", "hold"),
            # Map 'confidence' -> 'confidence_score'
            confidence_score=analysis_data.get("confidence", 0.0),
            # ใส่ข้อมูลอื่นๆ ที่ Manager อาจจะใช้
            analysis_summary=analysis_data.get("reason", "No reason provided"),
            metrics={} # Fundamental Agent ตัวใหม่ไม่ได้ส่ง metrics มา
        )

        return CanonicalAgentResponse(
            agent_type="fundamental",
            version="2.0",
            data=canonical_data,
            raw_metadata=raw_data,
        )
    except Exception as e:
        logger.warning(f"Validation failed for fundamental v2 response: {e}")
        return None

def normalize_response(raw_data: Dict[str, Any]) -> Optional[CanonicalAgentResponse]:
    """
    Acts as a factory to route and normalize an agent's response.
    """
    if not isinstance(raw_data, dict):
        logger.error("Invalid response format: not a dictionary.")
        return None

    # --- แก้ไข Logic การตรวจสอบ Agent Type ตรงนี้ ---

    # 1. เช็คว่าเป็น Standard Version หรือไม่
    if "version" in raw_data and "agent_type" in raw_data:
        normalized = _normalize_from_standard(raw_data)
        if normalized:
            return normalized

    # 2. ดึง agent key (รองรับทั้ง 'agent_type' และ 'agent')
    agent_identifier = raw_data.get("agent_type") or raw_data.get("agent")

    if agent_identifier == "technical":
        logger.info("Attempting fallback normalization for legacy technical agent.")
        return _normalize_from_legacy_technical(raw_data)

    elif agent_identifier == "fundamental_agent" or agent_identifier == "fundamental":
        # ตรวจสอบโครงสร้างเพื่อเลือกว่าจะใช้ Adapter ตัวไหน
        if "analysis" in raw_data.get("data", {}):
            logger.info("Normalizing using Fundamental V2 adapter.")
            return _normalize_from_fundamental_v2(raw_data)
        else:
            logger.info("Attempting fallback normalization for legacy fundamental agent.")
            return _normalize_from_legacy_fundamental(raw_data)

    # 3. Fallback
    logger.warning(
        f"Unable to normalize response for agent '{agent_identifier}'. "
        "No matching schema found."
    )
    return None
