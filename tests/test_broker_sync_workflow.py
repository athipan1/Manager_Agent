from pathlib import Path

import yaml


WORKFLOW_PATH = Path(".github/workflows/broker-sync-check.yml")
COMPOSE_PATH = Path("docker-compose.yml")


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_broker_sync_checks_out_unprofiled_compose_dependencies():
    workflow = _workflow_text()
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    required_agents = set()

    for service in (compose.get("services") or {}).values():
        if service.get("profiles"):
            continue
        build = service.get("build")
        context = build.get("context") if isinstance(build, dict) else build
        if isinstance(context, str) and context.startswith("../"):
            required_agents.add(Path(context).name)

    assert required_agents
    for agent in sorted(required_agents):
        assert f"Checkout {agent}" in workflow
        assert f"path: {agent}" in workflow
        assert f'echo "{agent}=$(git -C {agent} rev-parse HEAD)"' in workflow
