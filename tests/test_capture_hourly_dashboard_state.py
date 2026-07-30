import json

from scripts.capture_hourly_dashboard_state import build_dashboard_state


def test_dashboard_state_allowlists_real_paper_portfolio_data():
    preflight = {
        "status": "ready",
        "portfolio_cycle_id": "hourly-paper-1",
        "market_mode": "PORTFOLIO_REVIEW_ONLY",
        "runtime": {
            "paper_automation": True,
            "broker_mode": "ALPACA",
            "dry_run": False,
        },
    }
    broker_state = {
        "account": {
            "id": "private-account-id",
            "status": "ACTIVE",
            "cash": "48155.50",
            "equity": "71784.67",
            "buying_power": "275290.36",
        },
        "positions": [
            {
                "asset_id": "private-asset-id",
                "symbol": "acgl",
                "qty": "54",
                "avg_entry_price": "104.20",
                "current_price": "104.15",
                "market_value": "5624.10",
                "unrealized_pl": "-2.70",
                "strategy_bucket": "value_rebound",
            }
        ],
        "open_orders": [
            {
                "id": "private-order-id",
                "client_order_id": "private-client-id",
                "symbol": "acgl",
                "side": "sell",
                "qty": "54",
                "order_class": "bracket",
                "type": "limit",
                "status": "new",
                "limit_price": "112.84",
                "stop_price": "98.40",
            }
        ],
    }
    protection = {
        "positions": [
            {
                "symbol": "ACGL",
                "protection_status": "bracket_protected",
                "stop_covered_qty": "54",
                "take_profit_covered_qty": "54",
                "protective_orders": [{"order_id": "private-protection-order"}],
            }
        ]
    }

    report = build_dashboard_state(
        preflight=preflight,
        broker_state=broker_state,
        protection_diagnostics=protection,
    )

    assert report["runtime"] == {
        "mode": "PAPER",
        "brokerMode": "ALPACA",
        "dryRun": False,
        "liveTradingEnabled": False,
    }
    assert report["account"]["status"] == "ACTIVE"
    assert report["positions"][0]["symbol"] == "ACGL"
    assert report["positions"][0]["protection"]["hasBracket"] is True
    assert report["orders"][0]["symbol"] == "ACGL"
    assert report["summary"] == {"positionCount": 1, "openOrderCount": 1}

    serialized = json.dumps(report)
    assert "private-account-id" not in serialized
    assert "private-asset-id" not in serialized
    assert "private-order-id" not in serialized
    assert "private-client-id" not in serialized
    assert "private-protection-order" not in serialized


def test_simulator_dashboard_state_stays_dry_run():
    report = build_dashboard_state(
        preflight={
            "status": "ready",
            "runtime": {
                "paper_automation": False,
                "broker_mode": "SIMULATOR",
                "dry_run": True,
            },
        },
        broker_state={"account": {}, "positions": [], "open_orders": []},
        protection_diagnostics={"positions": []},
    )
    assert report["runtime"]["mode"] == "SIMULATOR"
    assert report["runtime"]["dryRun"] is True
    assert report["runtime"]["liveTradingEnabled"] is False
