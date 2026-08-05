from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIMULATOR_COMPOSE = ROOT / "docker-compose.hourly-simulator.yml"


def test_hourly_simulator_exercises_required_backtest_promotion_gate():
    compose = SIMULATOR_COMPOSE.read_text(encoding="utf-8")

    assert 'BROKER_MODE: SIMULATOR' in compose
    assert 'DRY_RUN: "true"' in compose
    assert 'BACKTEST_EXECUTION_GATE_REQUIRED: "true"' in compose
    assert 'BACKTEST_PROMOTION_AUTO_APPROVE_PAPER: "false"' in compose
    assert 'BACKTEST_PROMOTION_OBSERVATION_REQUIRED: "false"' in compose


def test_hourly_simulator_keeps_broker_mutation_disabled():
    compose = SIMULATOR_COMPOSE.read_text(encoding="utf-8")

    assert 'ALLOW_LIVE_TRADING: "false"' in compose
    assert 'PROFIT_AGENT_API_KEY: ${PROFIT_AGENT_API_KEY:?' in compose
