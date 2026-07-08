from scripts.export_dashboard_snapshot import build_snapshot


def test_build_snapshot_exports_frontend_safe_fields():
    report = {
        "generated_at": "2026-07-07T15:13:33+00:00",
        "mode": "ALPACA_PAPER",
        "broker_mode": "ALPACA",
        "flow": "discover_analyze_trade",
        "response": {
            "data": {
                "execution": {"status": "submitted", "reason": "orders placed"},
                "curator_signals": [
                    {
                        "symbol": "ACGL",
                        "status": "success",
                        "skill_name": "Hourly Backtest Reference Skill",
                        "execution": {
                            "execution_status": "success",
                            "output": {"confidence": 0.6338, "reason": "score passed threshold"},
                        },
                    }
                ],
            }
        },
        "broker_snapshot": {
            "account": {
                "data": {
                    "status": "ACTIVE",
                    "cash": "48155.50",
                    "equity": "71784.67",
                    "buying_power": "275290.36",
                    "account_id": "do-not-export",
                }
            },
            "positions": {
                "data": [
                    {
                        "symbol": "ACGL",
                        "qty": "54",
                        "avg_entry_price": "104.20",
                        "current_price": "104.155",
                        "market_value": "5624.37",
                        "unrealized_pl": "-2.43",
                        "strategy_bucket": "value_rebound",
                    }
                ]
            },
            "orders": {
                "data": [
                    {
                        "id": "do-not-export-order-id",
                        "broker_order_id": "do-not-export-broker-order-id",
                        "symbol": "ACGL",
                        "side": "sell",
                        "qty": "54",
                        "type": "limit",
                        "order_class": "bracket",
                        "status": "new",
                        "limit_price": "112.84",
                    }
                ]
            },
        },
        "protection_diagnostics": {
            "data": {
                "positions": [
                    {
                        "symbol": "ACGL",
                        "protection_status": "bracket_protected",
                        "has_protective_stop": True,
                        "has_take_profit": True,
                        "has_bracket": True,
                    }
                ]
            }
        },
    }

    snapshot = build_snapshot(report)

    assert snapshot["schemaVersion"] == "dashboard-snapshot.v1"
    assert snapshot["account"] == {
        "cash": 48155.5,
        "equity": 71784.67,
        "buyingPower": 275290.36,
        "status": "ACTIVE",
        "mode": "ALPACA_PAPER",
        "lastSyncedAt": "2026-07-07T15:13:33+00:00",
    }
    assert snapshot["positions"][0]["symbol"] == "ACGL"
    assert snapshot["positions"][0]["protection"] == {
        "status": "bracket_protected",
        "hasStopLoss": True,
        "hasTakeProfit": True,
        "hasBracket": True,
    }
    assert snapshot["openOrders"] == [
        {
            "symbol": "ACGL",
            "side": "sell",
            "quantity": 54.0,
            "orderClass": "bracket",
            "type": "limit",
            "status": "new",
            "takeProfit": 112.84,
            "stopLoss": True,
        }
    ]
    assert snapshot["curatorSignals"][0]["confidence"] == 0.6338
    assert "account_id" not in snapshot["account"]
    assert "broker_order_id" not in snapshot["openOrders"][0]
    assert "id" not in snapshot["openOrders"][0]
