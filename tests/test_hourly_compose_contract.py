from pathlib import Path

import yaml


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor(
    "!override",
    lambda loader, node: loader.construct_mapping(node)
    if isinstance(node, yaml.MappingNode)
    else loader.construct_sequence(node),
)


def load_compose(path):
    return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=ComposeLoader)


def test_paper_compose_routes_database_over_http_without_local_postgres_dependency():
    compose = load_compose("docker-compose.hourly-paper.yml")
    manager = compose["services"]["manager-agent"]
    execution = compose["services"]["execution-agent"]
    assert manager["environment"]["DATABASE_AGENT_URL"].startswith("${DATABASE_AGENT_URL:?")
    assert "database-agent" not in manager["depends_on"]
    assert execution["depends_on"] == {}
    assert execution["environment"]["DB_AGENT_URL"].startswith("${DATABASE_AGENT_URL:?")


def test_paper_compose_forces_exact_safety_and_required_gates():
    compose = load_compose("docker-compose.hourly-paper.yml")
    for service_name in ("manager-agent", "execution-agent"):
        env = compose["services"][service_name]["environment"]
        assert env["TRADING_MODE"] == "PAPER"
        assert env["BROKER_MODE"] == "ALPACA"
        assert env["DRY_RUN"] == "false"
        assert env["ALLOW_LIVE_TRADING"] == "false"
    manager_env = compose["services"]["manager-agent"]["environment"]
    assert manager_env["BACKTEST_EXECUTION_GATE_REQUIRED"] == "true"
    assert manager_env["BROKER_RECONCILE_REQUIRED"] == "true"
    assert manager_env["BROKER_RECONCILE_CONTEXT_REQUIRED"] == "true"
    assert manager_env["PERFORMANCE_SESSION_RISK_REQUIRED"] == "true"


def test_sqlite_is_confined_to_manual_simulator_override():
    paper = Path("docker-compose.hourly-paper.yml").read_text(encoding="utf-8")
    simulator = Path("docker-compose.hourly-simulator.yml").read_text(encoding="utf-8")
    assert "USE_SQLITE" not in paper
    assert "DATABASE_DEV_MODE" not in paper
    assert 'BROKER_MODE: SIMULATOR' in simulator
    assert 'USE_SQLITE: "true"' in simulator
