import pytest

import app.services.serialization_service as serialization_service


@pytest.fixture(autouse=True)
def normalize_simple_namespace_agent_responses(monkeypatch):
    original = serialization_service.response_to_dict

    def to_dict(resp):
        if hasattr(resp, "__dict__") and "data" in resp.__dict__:
            return dict(resp.__dict__)
        return original(resp)

    monkeypatch.setattr(serialization_service, "response_to_dict", to_dict)
