"""Fixture E2E for the Phase 18 managed/unmanaged portfolio boundary.

Uses fake agents and does not contact Alpaca or Railway.
"""
import scripts.hourly_portfolio_cycle as hourly
from app.unmanaged_broker_holdings import approved_unmanaged_symbols


class Agents:
    def __init__(self):
        self.execution, self.market, self.portfolio = object(), object(), object()
        self.technical, self.fundamental, self.profit = object(), object(), object()
        self.performance, self.database = object(), object()
        self.correlation_id = "phase18-e2e-fixture"
        self.posts = []

    def get(self, client, path):
        if path == "/broker/state?account_id=1":
            return {"data": {"account": {"equity": "100000", "cash": "40000"}, "positions": [
                {"symbol": "NVDA", "qty": "2", "avg_entry_price": "100", "current_price": "110"},
                {"symbol": "AAPL", "qty": "1", "avg_entry_price": "100", "current_price": "110"},
            ], "open_orders": []}}
        if path == "/broker/protection-diagnostics":
            return {"data": {"positions": [
                {"symbol": "NVDA", "protection_status": "unprotected", "unprotected_quantity": 2},
                {"symbol": "AAPL", "protection_status": "tp_sl_protected", "unprotected_quantity": 0},
            ]}}
        if path == "/accounts/1/fills?limit=500":
            return {"data": []}
        if path == "/accounts/1/positions":
            return {"data": [{"symbol": "AAPL", "strategy_bucket": "core_dividend"}]}
        raise AssertionError("Unexpected GET " + path)

    def post(self, client, path, payload):
        self.posts.append((client, path, payload))
        if client is self.market:
            return {"data": {"recommended_mode": "cash_heavy"}}
        if path == "/portfolio/allocation":
            return {"data": {"position_exposure": []}}
        if path == "/performance/session-risk":
            return {"data": {"emergency_halt": False}}
        if client is self.technical or client is self.fundamental:
            assert payload["ticker"] == "AAPL", "external symbol reached analysis"
            return {"data": {}}
        if path == "/profit/plan":
            assert payload["position"]["symbol"] == "AAPL"
            return {"data": {"primary_action": "hold"}}
        if path.startswith("/broker/cleanup/stale-open-orders?"):
            assert "dry_run=true" in path, "global cleanup could mutate external orders"
            return {"data": {"status": "dry_run"}}
        if path == "/review-history":
            return {"data": {"status": "success"}}
        raise AssertionError("Unexpected POST " + path)


def test_full_portfolio_parity_exposure_but_managed_only_decisions(monkeypatch):
    agents = Agents()
    monkeypatch.setattr(hourly, "_reconcile", lambda *args, **kwargs: {})
    monkeypatch.setattr(hourly, "market_regime_envelope_issues", lambda *args, **kwargs: [])
    monkeypatch.setattr(hourly, "evaluate_market_regime_gate", lambda *args, **kwargs: {
        "new_entries_allowed": False, "decision": "REVIEW"
    })
    report = hourly.review_existing_positions(
        agents,
        preflight={"portfolio_cycle_id": "phase18-e2e-fixture", "market_mode": "PAPER_REVIEW"},
        account_id="1",
        execute_safe_actions=True,
    )
    assert report["account"]["position_count"] == 2
    assert report["account"]["managed_position_count"] == 1
    assert report["account"]["unmanaged_position_count"] == 1
    assert report["unmanaged_positions"] == ["NVDA"]
    assert [x["symbol"] for x in report["position_decisions"]] == ["AAPL"]
    assert report["safe_for_candidate_analysis"] is True
    assert report["stale_order_cleanup_dry_run_for_external_scope"] is True
    allocation = next(p for c, path, p in agents.posts if path == "/portfolio/allocation")
    assert {x["symbol"] for x in allocation["positions"]} == {"NVDA", "AAPL"}
    assert approved_unmanaged_symbols(1) & {"NVDA"}
