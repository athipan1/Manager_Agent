import pytest
from app.adapters.service import normalize_response
from app.models import CanonicalAgentResponse

# --- Test Data ---

STANDARD_SUCCESS_RESPONSE = {
    "status": "success",
    "agent_type": "technical",
    "version": "2.1",
    "timestamp": "2023-10-27T10:00:00Z",
    "data": {
        "action": "buy",
        "confidence_score": 0.88,
        "reason": "Price crossed 50-day moving average.",
        "some_extra_data": "value"
    }
}

STANDARD_ERROR_RESPONSE = {
    "status": "error",
    "agent_type": "fundamental",
    "version": "1.5",
    "timestamp": "2023-10-27T10:05:00Z",
    "error": {
        "code": 5001,
        "message": "Failed to fetch data from external API."
    },
    # Data is required, even in an error case, for the model to parse.
    # The service under test should ignore this and use fallback values.
    "data": {
        "action": "buy",
        "confidence_score": 0.9,
        "reason": "This data should be ignored."
    }
}


INVALID_RESPONSE_VALIDATION_ERROR = {
    "status": "success",
    "agent_type": "technical",
    "version": "1.0",
    "timestamp": "2023-10-27T10:00:00Z",
    "data": {
        "action": "buy",
        # confidence_score is out of bounds (0-1)
        "confidence_score": 99.0,
        "reason": "This will fail validation."
    }
}


# --- Test Cases ---

def test_normalize_standard_success():
    """Tests successful normalization of a valid standard response."""
    result = normalize_response(STANDARD_SUCCESS_RESPONSE)
    assert isinstance(result, CanonicalAgentResponse)
    assert result.agent_type == "technical"
    assert result.version == "2.1"
    assert result.data.action == "buy"
    assert result.data.confidence_score == 0.88
    # Check that extra data is preserved
    assert result.data.some_extra_data == "value"
    assert result.error is None
    assert result.raw_metadata == STANDARD_SUCCESS_RESPONSE

def test_normalize_standard_error():
    """Tests normalization of a standard response with a status of 'error'."""
    result = normalize_response(STANDARD_ERROR_RESPONSE)
    assert isinstance(result, CanonicalAgentResponse)
    assert result.agent_type == "fundamental"
    assert result.version == "1.5"
    # Verify the fallback behavior for the 'data' field
    assert result.data.action == "hold"
    assert result.data.confidence_score == 0.0
    assert "Failed to fetch" in result.data.reason
    # Verify the 'error' field is correctly populated
    assert result.error is not None
    assert result.error["code"] == 5001
    assert result.error["message"] == "Failed to fetch data from external API."
    assert result.raw_metadata == STANDARD_ERROR_RESPONSE

def test_normalize_returns_none_for_validation_error():
    """Tests that normalization fails gracefully for responses that fail Pydantic validation."""
    result = normalize_response(INVALID_RESPONSE_VALIDATION_ERROR)
    assert result is None

def test_normalize_handles_non_dict_input():
    """Tests that the normalizer handles non-dictionary inputs safely."""
    assert normalize_response("just a string") is None
    assert normalize_response(None) is None
    assert normalize_response([1, 2, 3]) is None
