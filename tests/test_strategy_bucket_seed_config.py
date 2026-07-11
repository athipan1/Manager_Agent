import json
from pathlib import Path


EXPECTED_ASSIGNMENTS = {
    "ACGL": "value_rebound",
    "ADBE": "value_rebound",
    "BKNG": "value_rebound",
    "CINF": "value_rebound",
}


def test_hourly_compose_seeds_all_confirmed_held_position_buckets():
    compose_text = Path("docker-compose.curator.yml").read_text(encoding="utf-8")

    assert "STRATEGY_BUCKET_ASSIGNMENTS_JSON" in compose_text
    for symbol, bucket in EXPECTED_ASSIGNMENTS.items():
        assert f"{symbol}={bucket}" in compose_text


def test_versioned_registry_matches_compose_seed():
    registry = json.loads(
        Path("config/strategy_bucket_assignments.v1.json").read_text(encoding="utf-8")
    )

    assert registry["schema_version"] == "strategy-bucket-assignments.v1"
    assert registry["account_id"] == 1
    assert registry["assignments"] == EXPECTED_ASSIGNMENTS
    assert registry["safety"]["environment"] == "ALPACA_PAPER"
    assert registry["safety"]["live_trading_authorized"] is False
    assert registry["safety"]["manual_review_required_for_changes"] is True


def test_hourly_workflow_uses_curator_compose_override():
    workflow_text = Path(".github/workflows/hourly-auto-trading.yml").read_text(
        encoding="utf-8"
    )

    assert "docker-compose.curator.yml" in workflow_text
