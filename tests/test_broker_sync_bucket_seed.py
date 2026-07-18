import json
from pathlib import Path

import yaml


WORKFLOW_PATH = Path(".github/workflows/broker-sync-check.yml")
OVERRIDE_PATH = Path("docker-compose.broker-sync.yml")
REGISTRY_PATH = Path("config/strategy_bucket_assignments.v1.json")


def _expected_assignment_seed() -> str:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return ",".join(
        f"{symbol}={bucket}"
        for symbol, bucket in registry["assignments"].items()
    )


def test_broker_sync_workflow_loads_bucket_seed_override():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "COMPOSE_FILE: docker-compose.yml:docker-compose.broker-sync.yml" in workflow


def test_broker_sync_override_seeds_confirmed_paper_holdings():
    compose = yaml.safe_load(OVERRIDE_PATH.read_text(encoding="utf-8"))
    configured = compose["services"]["database-agent"]["environment"][
        "STRATEGY_BUCKET_ASSIGNMENTS_JSON"
    ]

    assert configured == (
        "${STRATEGY_BUCKET_ASSIGNMENTS_JSON:-"
        f"{_expected_assignment_seed()}"
        "}"
    )
