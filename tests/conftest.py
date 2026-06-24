import pytest

import app.main as manager


@pytest.fixture(autouse=True)
def normalize_simple_namespace_agent_responses(monkeypatch):
    original = manager._response_to_dict

    def _patched_response_to_dict(resp):
        if hasattr(resp, "__dict__") and "data" in resp.__dict__:
            return dict(resp.__dict__)
        return original(resp)

    monkeypatch.setattr(manager, "_response_to_dict", _patched_response_to_dict)
