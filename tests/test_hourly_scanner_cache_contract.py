from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "hourly-auto-trading.yml"
PAPER_COMPOSE = ROOT / "docker-compose.hourly-paper.yml"


def test_hourly_paper_restores_scanner_fundamental_cache():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Restore persistent Scanner fundamental cache" in workflow
    assert "uses: actions/cache@v4" in workflow
    assert "path: Manager_Agent/.cache/scanner/fundamentals" in workflow
    assert "scanner-fundamental-v1-${{ runner.os }}-${{ github.ref_name }}-${{ github.run_id }}" in workflow
    assert "if: steps.preflight.outputs.paper_automation == 'true'" in workflow


def test_hourly_paper_mounts_only_slow_fundamental_cache():
    compose = PAPER_COMPOSE.read_text(encoding="utf-8")

    assert 'SCANNER_FUNDAMENTAL_CACHE_ENABLED: "true"' in compose
    assert "SCANNER_FUNDAMENTAL_CACHE_TTL_SECONDS: ${SCANNER_FUNDAMENTAL_CACHE_TTL_SECONDS:-21600}" in compose
    assert "SCANNER_FUNDAMENTAL_CACHE_DIR: /code/.cache/scanner/fundamentals" in compose
    assert "./.cache/scanner/fundamentals:/code/.cache/scanner/fundamentals" in compose
    assert 'SCANNER_REQUIRE_REAL_MARKET_DATA: "true"' in compose
    assert 'SCANNER_OPPORTUNITY_REQUIRE_LIVE_SPREAD: "true"' in compose


def test_cache_change_does_not_break_host_side_market_regime_healthcheck():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "MARKET_REGIME_AGENT_URL: http://localhost:8014" in workflow
    assert "operator_confirmation:" in workflow
    assert 'description: "Explicit Paper execution confirmation from the caller"' in workflow
    assert "type: string" in workflow
