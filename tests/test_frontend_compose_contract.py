from pathlib import Path

import yaml


def load_compose(path):
    content = Path(path).read_text(encoding="utf-8").replace("!override", "")
    return yaml.safe_load(content)


def test_frontend_is_an_optional_dashboard_profile():
    compose = load_compose("docker-compose.frontend.yml")
    frontend = compose["services"]["trading-frontend"]
    manager = compose["services"]["manager-agent"]

    assert frontend["profiles"] == ["dashboard"]
    assert frontend["depends_on"] == {"manager-agent": {"condition": "service_healthy"}}
    assert "depends_on" not in manager
    assert frontend["restart"] == "unless-stopped"


def test_frontend_uses_same_origin_manager_proxy_not_docker_hostname_in_browser():
    frontend = load_compose("docker-compose.frontend.yml")["services"]["trading-frontend"]
    args = frontend["build"]["args"]
    assert args["VITE_DATA_SOURCE"] == "manager-api"
    assert args["VITE_MANAGER_API_URL"] == "/api"
    assert frontend["environment"]["MANAGER_UPSTREAM"] == "http://manager-agent:80"


def test_hourly_runtime_has_no_frontend_dependency():
    hourly_workflow = Path(".github/workflows/hourly-auto-trading.yml").read_text(encoding="utf-8")
    paper_compose = Path("docker-compose.hourly-paper.yml").read_text(encoding="utf-8")
    simulator_compose = Path("docker-compose.hourly-simulator.yml").read_text(encoding="utf-8")

    assert "trading-frontend" not in hourly_workflow
    assert "trading-frontend" not in paper_compose
    assert "trading-frontend" not in simulator_compose


def test_full_system_e2e_starts_manager_health_dependencies():
    compose = load_compose("docker-compose.frontend-e2e.yml")
    manager_dependencies = compose["services"]["manager-agent"]["depends_on"]
    workflow = Path(".github/workflows/frontend-dashboard-e2e.yml").read_text(encoding="utf-8")

    assert manager_dependencies == {
        "database-agent": {"condition": "service_healthy"},
        "execution-agent": {"condition": "service_healthy"},
        "risk-agent": {"condition": "service_healthy"},
    }
    assert "repository: athipan1/Risk_Agent" in workflow
    assert "database-agent execution-agent risk-agent manager-agent trading-frontend" in workflow
