from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as manager


class FakeScannerAgentClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def discover_best_fundamentals(self, correlation_id, max_universe=1000, top_n=10, exchange="NASDAQ", max_workers=10):
        candidates = [
            _candidate("KO", "core_dividend"),
            _candidate("ACGL", "value_rebound"),
            _candidate("MSFT", "news_momentum"),
        ]
        return SimpleNamespace(data={"candidates": candidates, "metadata": {"source": "fake_scanner"}}, error=None)


class FakeDatabaseAgentClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_account_balance(self, account_id, correlation_id):
        return SimpleNamespace(cash_balance=Decimal("100000"))

    async def get_positions(self, account_id, correlation_id):
        return []

    async def get_orders(self, account_id, correlation_id):
        return []

    async def get_session_risk_snapshot(self, account_id, correlation_id, symbol=None):
        return {
            "daily_realized_pnl": 0.0,
            "weekly_realized_pnl": 0.0,
            "consecutive_losses": 0,
            "trades_today": 0,
            "symbol_trades_today": 0,
            "emergency_halt": False,
        }

    async def save_signal(self, **kwargs):
        return None

    async def create_risk_approval(self, payload, correlation_id):
        return {**payload, "status": "approved"}


class FakeExecutionAgentClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def validate_order_batch(self, order_details, correlation_id):
        return SimpleNamespace(data={"approved": True, "orders": [order.model_dump(mode="json") for order in order_details]})

    async def execute_order_batch(self, order_details, correlation_id):
        created = [
            {
                "symbol": order.symbol,
                "strategy_bucket": order.strategy_bucket,
                "order": order.model_dump(mode="json"),
                "execution_job": {"status": "queued"},
            }
            for order in order_details
        ]
        return SimpleNamespace(data={"approved": True, "created": created, "failed": []})


def _candidate(symbol, bucket):
    return {
        "symbol": symbol,
        "candidate_score": 0.9,
        "recommendation_hint": "FUNDAMENTAL_TOP_10",
        "tags": [f"bucket-hint:{bucket}"],
        "raw_scores": {"quality_score": 90, "growth_score": 90, "valuation_score": 90},
        "metadata": {
            "primary_strategy_bucket_hint": bucket,
            "strategy_bucket_hints": [bucket],
            "bucket_hint_scores": {bucket: 0.9},
            "sector": "Technology" if bucket == "news_momentum" else "Consumer Defensive",
        },
    }


async def fake_call_agents(ticker, correlation_id):
    technical = {
        "status": "success",
        "data": {
            "action": "buy",
            "confidence_score": 0.92,
            "reason": f"{ticker} technical buy",
            "current_price": 100.0,
            "indicators": {"stop_loss": 90.0},
        },
    }
    fundamental = {
        "status": "success",
        "data": {
            "action": "buy",
            "confidence_score": 0.88,
            "reason": f"{ticker} fundamental buy",
            "sector": "Technology" if ticker == "MSFT" else "Consumer Defensive",
        },
    }
    return technical, fundamental


def fake_evaluate_risk(payload):
    symbol = payload["symbol"]
    return {
        "status": "approved",
        "data": {
            "approved": True,
            "final_quantity": 10,
            "approved_quantity": 10,
            "risk_approval_id": f"risk-{symbol}",
            "guard_plan": {"source": "fake_risk", "stop_loss": payload["protection_price"]},
            "violations": [],
            "warnings": [],
        },
    }


def test_discover_analyze_trade_returns_portfolio_contract(monkeypatch):
    monkeypatch.setattr(manager, "ScannerAgentClient", FakeScannerAgentClient)
    monkeypatch.setattr(manager, "DatabaseAgentClient", FakeDatabaseAgentClient)
    monkeypatch.setattr(manager, "ExecutionAgentClient", FakeExecutionAgentClient)
    monkeypatch.setattr(manager, "call_agents", fake_call_agents)
    monkeypatch.setattr("app.risk_manager.evaluate_risk", fake_evaluate_risk)
    monkeypatch.setattr(manager.config, "MANUAL_APPROVAL_REQUIRED", False)
    monkeypatch.setattr(manager.config, "TRADING_ENABLED", True)

    client = TestClient(manager.app)
    response = client.post(
        "/discover-analyze-trade",
        json={
            "account_id": "1",
            "max_universe": 3,
            "top_n": 3,
            "exchange": "NASDAQ",
            "max_workers": 1,
            "min_final_score": 0.55,
            "execute": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    data = body["data"]

    assert data["mode"] == "portfolio_allocation"
    assert data["allocation_plan"]["policy_name"] == "core_satellite_50_30_20"
    assert data["allocation_plan"]["buckets"]["core_dividend"]["target_weight"] == 0.5
    assert data["allocation_plan"]["buckets"]["value_rebound"]["target_weight"] == 0.3
    assert data["allocation_plan"]["buckets"]["news_momentum"]["target_weight"] == 0.2

    assert [position["symbol"] for position in data["selected_positions"]] == ["KO", "ACGL", "MSFT"]
    assert {position["strategy_bucket"] for position in data["selected_positions"]} == {"core_dividend", "value_rebound", "news_momentum"}

    assert len(data["risk_approvals"]) == 3
    assert len(data["execution_candidates"]) == 3
    assert data["execution"]["status"] == "submitted"
    assert len(data["execution"]["created"]) == 3
    assert data["portfolio_summary"]["selected_positions"] == 3
    assert data["portfolio_summary"]["approved_positions"] == 3

    assert "winner" not in data
    assert "trade_decision" not in data
    assert "legacy" in data
