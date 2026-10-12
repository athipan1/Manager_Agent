"""Read-only two-box UI ownership contract. No trading permission implied."""
from app.dashboard_snapshot import build_dashboard_snapshot


def _payload(*, is_synced=True, data_source="database"):
    return {
        "account_id": "1",
        "data_source": data_source,
        "positions": [
            {"symbol": "OXY", "quantity": "2.5", "strategy_bucket": "unassigned"},
            {"symbol": "MSFT", "quantity": "3", "strategy_bucket": "quality_growth"},
            {"symbol": "UNKN", "quantity": "1", "strategy_bucket": "quality_growth"},
        ],
        "database_sync": {
            "mismatch": {"is_synced": is_synced},
            "database": {
                "strategy_bucket_assignments": [
                    {"symbol": "MSFT", "strategy_bucket": "quality_growth"},
                ],
            },
        },
    }


def test_reviewed_manual_ownership_and_verified_strategy_assignment(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("BROKER_MODE", "ALPACA")
    items = build_dashboard_snapshot(_payload()).positions
    assert {row.symbol: row.ownership for row in items} == {
        "OXY": "manual",
        "MSFT": "ai_managed",
        "UNKN": "unclassified",
    }


def test_unsynced_or_broker_fallback_never_promotes_ai_owner(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("BROKER_MODE", "ALPACA")
    for payload in (_payload(is_synced=False), _payload(data_source="broker_fallback")):
        items = build_dashboard_snapshot(payload).positions
        assert {row.symbol: row.ownership for row in items} == {
            "OXY": "manual", "MSFT": "unclassified", "UNKN": "unclassified",
        }


def test_simulator_or_live_context_never_inherits_alpaca_paper_ownership(monkeypatch):
    for mode, broker in (("LIVE", "ALPACA"), ("PAPER", "SIMULATOR")):
        monkeypatch.setenv("TRADING_MODE", mode)
        monkeypatch.setenv("BROKER_MODE", broker)
        items = build_dashboard_snapshot(_payload()).positions
        assert all(row.ownership == "unclassified" for row in items)
