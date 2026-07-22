from datetime import datetime, timedelta, timezone

from app.profit_market_context import compose_profit_market_context


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def _market(**overrides):
    projection = {
        "context_version": "profit-market-context.v1",
        "regime": "bull",
        "risk_level": "medium",
        "atr_pct": 0.025,
        "volatility_percentile": 65,
        "trend_strength": 0.60,
        "observed_at": (NOW - timedelta(seconds=20)).isoformat(),
        "source": "market-regime-agent",
    }
    projection.update(overrides)
    return {"profit_policy_context": projection}


def _technical(**overrides):
    projection = {
        "context_version": "profit-technical-context.v1",
        "atr_pct": 0.03,
        "trend_strength": 0.78,
        "volume_strength": 0.70,
        "observed_at": (NOW - timedelta(seconds=10)).isoformat(),
        "evidence_status": "complete",
        "source": "technical-agent",
    }
    projection.update(overrides)
    return {"profit_policy_context": projection}


def _position(**overrides):
    position = {
        "highest_price_since_entry": 120,
        "highest_price_since_entry_source": "database_agent",
        "opened_at": (NOW - timedelta(days=12)).isoformat(),
    }
    position.update(overrides)
    return position


def test_composes_versioned_market_and_technical_evidence():
    result = compose_profit_market_context(
        market_regime=_market(),
        technical_analysis=_technical(),
        position=_position(),
        lifecycle_available=True,
        now=NOW,
    )

    assert result["market_context"] == {
        "regime": "BULL",
        "risk_level": "MEDIUM",
        "atr_pct": 0.03,
        "volatility_percentile": 65,
        "trend_strength": 0.78,
        "volume_strength": 0.70,
        "observed_at": "2026-07-22T11:59:40Z",
        "holding_days": 12,
    }
    assert result["data_quality"] == {
        "market_price_fresh": True,
        "peak_history_complete": True,
        "position_version_current": True,
        "emergency_halt_active": False,
    }
    assert result["warnings"] == []


def test_does_not_fabricate_missing_technical_fields():
    result = compose_profit_market_context(
        market_regime=_market(),
        technical_analysis={},
        position=_position(),
        lifecycle_available=True,
        now=NOW,
    )

    assert "volume_strength" not in result["market_context"]
    assert result["market_context"]["trend_strength"] == 0.60
    assert any(
        "Technical profit context is unavailable" in warning
        for warning in result["warnings"]
    )


def test_stale_evidence_missing_peak_and_version_fail_quality():
    result = compose_profit_market_context(
        market_regime=_market(
            observed_at=(NOW - timedelta(seconds=121)).isoformat()
        ),
        technical_analysis=_technical(),
        position=_position(
            highest_price_since_entry=None,
            highest_price_since_entry_source="current_price_fallback",
        ),
        lifecycle_available=False,
        max_age_seconds=120,
        now=NOW,
    )

    assert result["data_quality"]["market_price_fresh"] is False
    assert result["data_quality"]["peak_history_complete"] is False
    assert result["data_quality"]["position_version_current"] is False
    assert len(result["warnings"]) == 3


def test_unsupported_market_contract_blocks_adaptation():
    result = compose_profit_market_context(
        market_regime=_market(context_version="profit-market-context.v0"),
        technical_analysis=_technical(),
        position=_position(),
        lifecycle_available=True,
        now=NOW,
    )

    assert "market_context" not in result
    assert result["data_quality"]["market_price_fresh"] is False
    assert any("unsupported version" in warning for warning in result["warnings"])


def test_technical_fields_without_timestamp_fail_freshness():
    result = compose_profit_market_context(
        market_regime=_market(),
        technical_analysis=_technical(observed_at=None),
        position=_position(),
        lifecycle_available=True,
        now=NOW,
    )

    assert result["market_context"]["volume_strength"] == 0.70
    assert result["data_quality"]["market_price_fresh"] is False


def test_insufficient_technical_evidence_is_not_forwarded():
    result = compose_profit_market_context(
        market_regime=_market(),
        technical_analysis=_technical(
            evidence_status="insufficient", volume_strength=0.99
        ),
        position=_position(),
        lifecycle_available=True,
        now=NOW,
    )

    assert "volume_strength" not in result["market_context"]
    assert any("lacks usable evidence" in warning for warning in result["warnings"])


def test_explicit_event_risk_and_emergency_halt_are_preserved():
    result = compose_profit_market_context(
        market_regime=_market(),
        technical_analysis=_technical(),
        position=_position(upcoming_event_risk=True),
        lifecycle_available=True,
        emergency_halt_active=True,
        now=NOW,
    )

    assert result["market_context"]["upcoming_event_risk"] is True
    assert result["data_quality"]["emergency_halt_active"] is True
