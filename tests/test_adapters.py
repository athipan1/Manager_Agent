import pytest
from app.adapters import adapt
from app.models import CanonicalAgentResponse

# Sample valid raw data from agents
SAMPLE_TECH_RESPONSE_V1 = {
    "agent_type": "technical",
    "ticker": "AAPL",
    "status": "success",
    "data": {
        "current_price": 150.0,
        "action": "buy",
        "confidence_score": 0.85,
        "indicators": {
            "rsi": 65,
            "macd": "bullish",
            "stop_loss": 140.0
        }
    }
}

SAMPLE_FUND_RESPONSE_V1 = {
    "agent_type": "fundamental",
    "ticker": "AAPL",
    "status": "success",
    "data": {
        "action": "buy",
        "confidence_score": 0.90,
        "analysis_summary": "Strong quarterly earnings.",
        "metrics": {
            "pe_ratio": 25.0,
            "eps": 6.0
        }
    }
}

# Sample invalid/malformed data
INVALID_TECH_RESPONSE = {
    "agent_type": "technical",
    "ticker": "MSFT",
    "data": {
        # Missing "action" and "confidence_score"
        "current_price": 300.0,
    }
}

UNKNOWN_AGENT_RESPONSE = {
    "agent_type": "unknown",
    "data": {}
}


def test_adapt_technical_v1_success():
    """Test successful adaptation of a valid v1 technical agent response."""
    result = adapt(SAMPLE_TECH_RESPONSE_V1)
    assert isinstance(result, CanonicalAgentResponse)
    assert result.agent_type == "technical"
    assert result.action == "buy"
    assert result.score == 0.85
    assert result.metadata["current_price"] == 150.0
    assert result.metadata["stop_loss"] == 140.0
    assert "rsi" in result.metadata["indicators"]


def test_adapt_fundamental_v1_success():
    """Test successful adaptation of a valid v1 fundamental agent response."""
    result = adapt(SAMPLE_FUND_RESPONSE_V1)
    assert isinstance(result, CanonicalAgentResponse)
    assert result.agent_type == "fundamental"
    assert result.action == "buy"
    assert result.score == 0.90
    assert result.metadata["analysis_summary"] == "Strong quarterly earnings."
    assert result.metadata["metrics"]["pe_ratio"] == 25.0


def test_adapt_invalid_data_returns_none():
    """Test that malformed data for a known agent type returns None."""
    result = adapt(INVALID_TECH_RESPONSE)
    assert result is None


def test_adapt_unknown_agent_type_returns_none():
    """Test that an unknown agent type returns None."""
    result = adapt(UNKNOWN_AGENT_RESPONSE)
    assert result is None


def test_adapt_empty_dict_returns_none():
    """Test that an empty dictionary returns None gracefully."""
    result = adapt({})
    assert result is None
