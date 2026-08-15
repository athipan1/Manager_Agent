import pytest

from app import agent_client


def test_build_agent_request_bodies_sends_explicit_daily_timeframe(monkeypatch):
    monkeypatch.setattr(
        agent_client,
        "get_scanner_prefetch",
        lambda ticker: None,
    )

    technical, fundamental = agent_client.build_agent_request_bodies("AAPL")

    assert technical == {
        "ticker": "AAPL",
        "timeframe": "1d",
    }
    assert fundamental["ticker"] == "AAPL"
    assert fundamental["period"] == "1mo"
    assert "timeframe" not in fundamental


def test_build_agent_request_bodies_supports_explicit_intraday_timeframe(monkeypatch):
    monkeypatch.setattr(
        agent_client,
        "get_scanner_prefetch",
        lambda ticker: None,
    )

    technical, _ = agent_client.build_agent_request_bodies(
        "MSFT",
        technical_timeframe="1H",
    )

    assert technical == {
        "ticker": "MSFT",
        "timeframe": "1h",
    }


def test_build_agent_request_bodies_rejects_unsupported_timeframe(monkeypatch):
    monkeypatch.setattr(
        agent_client,
        "get_scanner_prefetch",
        lambda ticker: None,
    )

    with pytest.raises(ValueError, match="Unsupported technical timeframe"):
        agent_client.build_agent_request_bodies(
            "AAPL",
            technical_timeframe="2h",
        )


def test_scanner_prefetch_is_only_sent_to_fundamental():
    context = {
        "symbol": "NVDA",
        "source": "scanner",
    }

    technical, fundamental = agent_client.build_agent_request_bodies(
        "NVDA",
        technical_timeframe="30m",
        fundamental_context=context,
    )

    assert technical == {
        "ticker": "NVDA",
        "timeframe": "30m",
    }
    assert "prefetched_data" not in technical
    assert fundamental["prefetched_data"] == context
    assert "timeframe" not in fundamental
