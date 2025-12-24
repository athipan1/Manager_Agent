import pytest
from app.adapters.service import normalize_response
from app.models import CanonicalAgentResponse

# --- Test Data ---

LEGACY_TECH_RESPONSE_VALID = {
    "status": "success",
    "agent_type": "technical",
    "ticker": "AOT.BK",
    "data": {
        "current_price": 68.25,
        "action": "buy",
        "confidence_score": 0.78,
        "indicators": {"trend": "uptrend", "rsi": 62.4}
    }
}

LEGACY_FUND_RESPONSE_VALID = {
    "status": "success",
    "agent_type": "fundamental",
    "ticker": "AOT.BK",
    "data": {
        "action": "hold",
        "confidence_score": 0.65,
        "analysis_summary": "Solid but fairly valued.",
        "metrics": {"pe_ratio": 15.5}
    }
}

STANDARD_SENTIMENT_RESPONSE_VALID = {
    "status": "success",
    "agent_type": "sentiment",
    "version": "1.0",
    "timestamp": "2023-10-27T10:00:00Z",
    "data": {
        "action": "buy",
        "confidence_score": 0.88,
        "reason": "High positive sentiment detected.",
        "sentiment_score": 0.92
    }
}

INVALID_RESPONSE_MISSING_TYPE = {
    "status": "success",
    "data": {"action": "buy", "confidence_score": 0.5}
}

INVALID_RESPONSE_BAD_DATA = {
    "status": "success",
    "agent_type": "technical",
    "data": {"action": "invalid_action", "confidence_score": 99.0}
}

# --- Test Cases ---

def test_normalize_legacy_technical_success():
    """Tests successful normalization of a valid legacy technical response."""
    result = normalize_response(LEGACY_TECH_RESPONSE_VALID)
    assert isinstance(result, CanonicalAgentResponse)
    assert result.agent_type == "technical"
    assert result.version == "1.0-legacy"
    assert result.data.action == "buy"
    assert result.data.confidence_score == 0.78
    assert result.data.current_price == 68.25
    assert "trend" in result.data.indicators

def test_normalize_legacy_fundamental_success():
    """Tests successful normalization of a valid legacy fundamental response."""
    result = normalize_response(LEGACY_FUND_RESPONSE_VALID)
    assert isinstance(result, CanonicalAgentResponse)
    assert result.agent_type == "fundamental"
    assert result.version == "1.0-legacy"
    assert result.data.action == "hold"
    assert result.data.confidence_score == 0.65
    assert "fairly valued" in result.data.analysis_summary

def test_normalize_standard_response_success():
    """Tests successful normalization of a valid standard (versioned) response."""
    result = normalize_response(STANDARD_SENTIMENT_RESPONSE_VALID)
    assert isinstance(result, CanonicalAgentResponse)
    assert result.agent_type == "sentiment"
    assert result.version == "1.0"
    assert result.data.action == "buy"
    assert result.data.confidence_score == 0.88
    assert result.data.sentiment_score == 0.92

def test_normalize_returns_none_for_missing_agent_type():
    """Tests that normalization fails gracefully for responses with no agent_type."""
    result = normalize_response(INVALID_RESPONSE_MISSING_TYPE)
    assert result is None

def test_normalize_returns_none_for_invalid_data():
    """Tests that normalization fails gracefully for responses with malformed data."""
    result = normalize_response(INVALID_RESPONSE_BAD_DATA)
    assert result is None

def test_normalize_returns_none_for_unknown_agent_type():
    """Tests that normalization fails for an unknown agent type that isn't legacy."""
    unknown_agent_response = LEGACY_TECH_RESPONSE_VALID.copy()
    unknown_agent_response["agent_type"] = "unknown_agent"
    result = normalize_response(unknown_agent_response)
    assert result is None

def test_normalize_handles_non_dict_input():
    """Tests that the normalizer handles non-dictionary inputs safely."""
    assert normalize_response("just a string") is None
    assert normalize_response(None) is None
    assert normalize_response([1, 2, 3]) is None
