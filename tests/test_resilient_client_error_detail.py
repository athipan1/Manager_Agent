import pytest

from app.resilient_client import ResilientAgentClient, _extract_agent_error_message


def client_without_transport():
    client = object.__new__(ResilientAgentClient)
    client.base_url = "http://technical-agent:8002"
    return client


def test_extract_agent_error_message_supports_detail_and_nested_errors():
    assert _extract_agent_error_message({"detail": "price history missing"}) == "price history missing"
    assert _extract_agent_error_message(
        {"errors": [{"message": "indicator calculation failed"}]}
    ) == "indicator calculation failed"


def test_validate_standard_response_preserves_agent_and_error_detail():
    response = {
        "status": "error",
        "agent_type": "technical-agent",
        "version": "1.0.0",
        "timestamp": "2026-07-14T17:48:00Z",
        "data": None,
        "metadata": {},
        "error": {"detail": "price history missing", "code": "NO_PRICE_DATA"},
    }

    with pytest.raises(
        ValueError,
        match="Agent technical-agent returned error status: price history missing",
    ):
        client_without_transport().validate_standard_response(response)


def test_validate_standard_response_serializes_unrecognized_error_shape():
    response = {
        "status": "error",
        "agent_type": "fundamental-agent",
        "version": "1.0.0",
        "timestamp": "2026-07-14T17:48:00Z",
        "error": {"code": "UPSTREAM_EMPTY"},
    }

    with pytest.raises(ValueError, match="UPSTREAM_EMPTY"):
        client_without_transport().validate_standard_response(response)
