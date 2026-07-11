from pathlib import Path


def test_hourly_compose_seeds_cinf_value_rebound_bucket():
    compose_text = Path("docker-compose.curator.yml").read_text(encoding="utf-8")

    assert "STRATEGY_BUCKET_ASSIGNMENTS_JSON" in compose_text
    assert "CINF=value_rebound" in compose_text


def test_hourly_workflow_uses_curator_compose_override():
    workflow_text = Path(".github/workflows/hourly-auto-trading.yml").read_text(
        encoding="utf-8"
    )

    assert "docker-compose.curator.yml" in workflow_text
