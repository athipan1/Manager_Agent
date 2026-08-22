from pathlib import Path


HOURLY_PAPER_COMPOSE = Path("docker-compose.hourly-paper.yml")


def test_hourly_paper_requires_scanner_opportunity_profile():
    compose = HOURLY_PAPER_COMPOSE.read_text(encoding="utf-8")

    assert 'SCANNER_REQUIRE_REAL_MARKET_DATA: "true"' in compose
    assert 'SCANNER_OPPORTUNITY_PROFILE_REQUIRED: "true"' in compose
