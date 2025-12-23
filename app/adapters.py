from typing import Dict, Any, Optional

from .models import CanonicalAgentResponse, TechnicalAgentResponse, FundamentalAgentResponse


def _adapt_technical_v1(raw_data: Dict[str, Any]) -> CanonicalAgentResponse:
    """Adapts a raw response from a v1 Technical Agent."""
    parsed_response = TechnicalAgentResponse(**raw_data)
    return CanonicalAgentResponse(
        agent_type=parsed_response.agent_type,
        action=parsed_response.data.action,
        score=parsed_response.data.confidence_score,
        metadata={
            "current_price": parsed_response.data.current_price,
            "stop_loss": parsed_response.data.indicators.get("stop_loss"),
            "indicators": parsed_response.data.indicators
        }
    )

def _adapt_fundamental_v1(raw_data: Dict[str, Any]) -> CanonicalAgentResponse:
    """Adapts a raw response from a v1 Fundamental Agent."""
    parsed_response = FundamentalAgentResponse(**raw_data)
    return CanonicalAgentResponse(
        agent_type=parsed_response.agent_type,
        action=parsed_response.data.action,
        score=parsed_response.data.confidence_score,
        metadata={
            "analysis_summary": parsed_response.data.analysis_summary,
            "metrics": parsed_response.data.metrics
        }
    )

def adapt(raw_data: Dict[str, Any]) -> Optional[CanonicalAgentResponse]:
    """
    Factory function to adapt a raw agent response to the canonical model.

    Inspects the raw data to determine the agent type and version,
    then delegates to the appropriate adapter function.
    """
    agent_type = raw_data.get("agent_type")

    try:
        if agent_type == "technical":
            return _adapt_technical_v1(raw_data)
        elif agent_type == "fundamental":
            return _adapt_fundamental_v1(raw_data)
        else:
            # Handle unknown agent types if necessary
            return None
    except Exception:
        # Gracefully handle parsing or adaptation errors
        return None
