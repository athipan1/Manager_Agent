from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.contracts import StandardAgentResponse
from app.resilient_client import AgentUnavailable
from app.scanner_client import (
    _scan_request_payload,
    _validate_scanner_market_data_contract,
)


ROOT = Path(__file__).resolve().parents[1]
PAPER_COMPOSE = ROOT / "docker-compose.hourly-paper.yml"
SIMULATOR_COMPOSE = ROOT / "docker-compose.hourly-simulator.yml"


def _response(
    *,
    correlation_id: str = "scanner-contract-test",
    source: str = "ranked_scanner",
    status: str = "success",
    error=None,
) -> StandardAgentResponse:
    return StandardAgentResponse(
        status=status,
        agent_type="scanner-agent",
        version="5.0.0",
        timestamp=datetime.now(timezone.utc),
        correlation_id=correlation_id,
        data={
            "candidates": [
                {
                    "symbol": "AAPL",
                    "recommendation": "BUY",
                    "metadata": {"source": source},
                }
            ]
        },
        error=error,
    )


def test_scan_payload_explicitly_targets_us_market(monkeypatch):
    monkeypatch.delenv("SCANNER_SCREENER", raising=False)
    monkeypatch.delenv("SCANNER_EXCHANGE", raising=False)

    assert _scan_request_payload(["AAPL"]) == {
        "symbols": ["AAPL"],
        "screener": "america",
        "exchange": "NASDAQ",
    }


def test_scan_payload_allows_deliberate_market_override(monkeypatch):
    monkeypatch.setenv("SCANNER_SCREENER", "THAILAND")
    monkeypatch.setenv("SCANNER_EXCHANGE", "set")

    assert _scan_request_payload(["PTT"]) == {
        "symbols": ["PTT"],
        "screener": "thailand",
        "exchange": "SET",
    }


def test_real_market_guard_is_opt_in(monkeypatch):
    monkeypatch.delenv("SCANNER_REQUIRE_REAL_MARKET_DATA", raising=False)

    _validate_scanner_market_data_contract(
        _response(source="dev_fallback"),
        "scanner-contract-test",
    )


def test_real_market_guard_accepts_ranked_scanner_response(monkeypatch):
    monkeypatch.setenv("SCANNER_REQUIRE_REAL_MARKET_DATA", "true")

    _validate_scanner_market_data_contract(
        _response(),
        "scanner-contract-test",
    )


@pytest.mark.parametrize("source", ["dev_fallback", "yfinance_market_data"])
def test_real_market_guard_rejects_known_fallback_sources(monkeypatch, source):
    monkeypatch.setenv("SCANNER_REQUIRE_REAL_MARKET_DATA", "true")

    with pytest.raises(AgentUnavailable, match="fallback candidates"):
        _validate_scanner_market_data_contract(
            _response(source=source),
            "scanner-contract-test",
        )


def test_real_market_guard_rejects_hidden_response_error(monkeypatch):
    monkeypatch.setenv("SCANNER_REQUIRE_REAL_MARKET_DATA", "true")

    with pytest.raises(AgentUnavailable, match="status=success"):
        _validate_scanner_market_data_contract(
            _response(error={"code": "provider_error", "message": "unauthorized"}),
            "scanner-contract-test",
        )


def test_real_market_guard_rejects_correlation_mismatch(monkeypatch):
    monkeypatch.setenv("SCANNER_REQUIRE_REAL_MARKET_DATA", "true")

    with pytest.raises(AgentUnavailable, match="correlation ID mismatch"):
        _validate_scanner_market_data_contract(
            _response(correlation_id="wrong-correlation"),
            "scanner-contract-test",
        )


def test_hourly_paper_compose_passes_real_scanner_credentials():
    compose = PAPER_COMPOSE.read_text(encoding="utf-8")

    assert 'SCANNER_REQUIRE_REAL_MARKET_DATA: "true"' in compose
    assert 'SCANNER_DEV_MODE: "false"' in compose
    assert "APCA_API_KEY_ID: ${ALPACA_API_KEY_ID:?" in compose
    assert "APCA_API_SECRET_KEY: ${ALPACA_SECRET_KEY:?" in compose


def test_hourly_simulator_keeps_execution_safe_but_scanner_fail_closed():
    compose = SIMULATOR_COMPOSE.read_text(encoding="utf-8")

    assert 'BROKER_MODE: SIMULATOR' in compose
    assert 'DRY_RUN: "true"' in compose
    assert 'SCANNER_REQUIRE_REAL_MARKET_DATA: "true"' in compose
    assert 'SCANNER_DEV_MODE: "false"' in compose
    assert "APCA_API_KEY_ID: ${ALPACA_API_KEY_ID:-}" in compose
    assert "APCA_API_SECRET_KEY: ${ALPACA_SECRET_KEY:-}" in compose
