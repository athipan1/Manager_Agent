import pytest

import app.services.serialization_service as serialization_service
from app.services.exposure_service import clear_position_snapshot


@pytest.fixture(autouse=True)
def normalize_simple_namespace_agent_responses(monkeypatch):
    original = serialization_service.response_to_dict

    def to_dict(resp):
        if hasattr(resp, "__dict__") and "data" in resp.__dict__:
            return dict(resp.__dict__)
        return original(resp)

    monkeypatch.setattr(serialization_service, "response_to_dict", to_dict)


@pytest.fixture(autouse=True)
def isolate_position_snapshot_context():
    clear_position_snapshot()
    yield
    clear_position_snapshot()
