from pathlib import Path

import pytest
import yaml

from scripts.full_system_profit_e2e import (
    DEFAULT_QUALITY,
    PositionCase,
    ProfitLifecycleE2E,
    TimeoutAfterAcceptGateway,
    decimal_value,
)
from scripts.profit_decision_orchestrator import GatewayTimeout


WORKFLOW_PATH = Path(".github/workflows/full-system-profit-e2e.yml")


def runner(tmp_path):
    return ProfitLifecycleE2E(
        database_url="http://database",
        database_api_key="database-key",
        profit_url="http://profit",
        profit_api_key="profit-key",
        risk_url="http://risk",
        execution_url="http://execution",
        execution_api_key="execution-key",
        compose_directory=tmp_path,
        compose_files=[tmp_path / "docker-compose.yml"],
        output_path=tmp_path / "report.json",
    )


def test_profit_payload_uses_database_lifecycle_and_exact_market_constraints(
    tmp_path,
):
    lifecycle = {
        "position_id": "account-101:position-9",
        "position_version": 3,
        "first_target_executed": True,
        "second_target_executed": False,
        "total_exited_quantity": 3,
        "remaining_quantity": 7,
    }

    payload = runner(tmp_path).profit_payload(
        PositionCase(
            account_id=101,
            symbol="ACGL",
            quantity=7,
            current_price=112,
            peak=120,
        ),
        lifecycle,
    )

    assert payload["schema_version"] == "profit-decision.v2"
    assert payload["lifecycle"] == lifecycle
    assert payload["data_quality"] == DEFAULT_QUALITY
    assert payload["market_constraints"] == {
        "price_increment": "0.01",
        "quantity_increment": "1",
        "minimum_order_quantity": "1",
    }


def test_timeout_injection_occurs_only_after_execution_accepts_request():
    class Delegate:
        def __init__(self):
            self.calls = []

        def request(self, service, method, path, **kwargs):
            self.calls.append((service, method, path))
            return {"status": "success", "data": {"accepted": True}}

    delegate = Delegate()
    gateway = TimeoutAfterAcceptGateway(delegate)

    assert gateway.request("database", "GET", "/health")["status"] == "success"
    with pytest.raises(GatewayTimeout, match="after acceptance"):
        gateway.request("execution", "POST", "/execute")
    assert gateway.request("execution", "POST", "/execute")["status"] == "success"
    assert delegate.calls == [
        ("database", "GET", "/health"),
        ("execution", "POST", "/execute"),
        ("execution", "POST", "/execute"),
    ]


@pytest.mark.parametrize("value", [1, 1.0, "1", "1.00000000"])
def test_decimal_value_accepts_database_numeric_json_shapes(value):
    assert decimal_value(value) == 1


def test_worker_uses_execution_container_virtualenv(tmp_path, monkeypatch):
    captured = {}

    class Completed:
        returncode = 0
        stdout = "worker completed"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(
        "scripts.full_system_profit_e2e.subprocess.run",
        fake_run,
    )

    output = runner(tmp_path).run_worker()

    assert "/opt/venv/bin/python" in captured["command"]
    assert captured["command"][-3:] == [
        "/opt/venv/bin/python",
        "-m",
        "app.workers.execution_worker",
    ]
    assert captured["kwargs"]["check"] is False
    assert output == "worker completed"


def test_full_system_profit_workflow_is_fail_closed_and_collects_evidence():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)

    assert parsed["name"] == "Full-System Profit E2E"
    for repository in (
        "athipan1/Database_Agent",
        "athipan1/Profit_Agent",
        "athipan1/Risk_Agent",
        "athipan1/Execution_Agent",
    ):
        assert f"repository: {repository}" in text
    assert "postgresql://user:password@db:5432/trading_db" in text
    assert 'USE_SQLITE: ""' in text
    assert "python -m scripts.full_system_profit_e2e" in text
    assert "actions/upload-artifact@v4" in text
    assert "if-no-files-found: error" in text
    assert "continue-on-error" not in text
