from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    *,
    expected_status: int | None = None,
    allowed_statuses: set[str] | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            status_code = response.status
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise AssertionError(
            f"{method} {url} failed with {exc.code}: {body}"
        ) from exc

    parsed = json.loads(body) if body else {}
    if expected_status is not None:
        assert status_code == expected_status, (method, url, status_code, parsed)
    allowed = allowed_statuses or {"success"}
    assert parsed.get("status") in allowed, {
        "method": method,
        "url": url,
        "status_code": status_code,
        "response": parsed,
    }
    return parsed


def check_risk_database_execution() -> None:
    risk_payload = {
        "account_id": 1,
        "symbol": "AAPL",
        "side": "buy",
        "entry_price": 100,
        "protection_price": 90,
        "requested_quantity": 1,
        "equity": 100000,
        "current_symbol_exposure": 0,
        "current_total_exposure": 0,
        "open_orders_exposure": 0,
        "margin_multiplier": 1,
        "trading_mode": "PAPER",
        "asset_class": "stock",
        "strategy_bucket": "unassigned",
        "daily_realized_pnl": 0,
        "weekly_realized_pnl": 0,
        "consecutive_losses": 0,
        "trades_today": 0,
        "symbol_trades_today": 0,
        "emergency_halt": False,
    }
    risk = request_json(
        "POST",
        "http://localhost:8007/risk/check",
        risk_payload,
        allowed_statuses={"success", "approved", "rejected"},
    )
    risk_data = risk.get("data") or {}
    assert isinstance(risk_data.get("approved"), bool), risk
    assert "final_quantity" in risk_data, risk

    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    approval_payload = {
        "approval_id": "contract-risk-db-order",
        "account_id": 1,
        "symbol": "AAPL",
        "side": "buy",
        "approved_quantity": 1,
        "expires_at": expires_at,
        "metadata": {"source": "agent-contract-e2e"},
    }
    database_headers = {"X-API-KEY": "dev_database_key"}
    request_json(
        "POST",
        "http://localhost:8004/risk-approvals",
        approval_payload,
        database_headers,
    )

    order_payload = {
        "trade_id": "contract-db-order-001",
        "client_order_id": "contract-db-order-001",
        "account_id": 1,
        "symbol": "AAPL",
        "side": "buy",
        "order_type": "market",
        "quantity": 1,
        "time_in_force": "GTC",
        "strategy_bucket": "unassigned",
        "risk_approval_id": "contract-risk-db-order",
        "final_quantity": 1,
        "guard_plan": {"trigger_price": 90, "take_profit_price": 120},
    }
    database_order = request_json(
        "POST",
        "http://localhost:8004/accounts/1/orders",
        order_payload,
        database_headers,
    )
    database_order_data = database_order.get("data") or {}
    assert database_order_data.get("trade_id") == "contract-db-order-001"
    assert database_order_data.get("order_id") is not None
    assert database_order_data.get("status") in {
        "pending",
        "placed",
        "executed",
        "failed",
        "cancelled",
        "partially_filled",
    }

    approval_payload["approval_id"] = "contract-risk-exec-order"
    request_json(
        "POST",
        "http://localhost:8004/risk-approvals",
        approval_payload,
        database_headers,
    )
    execution_payload = dict(order_payload)
    execution_payload.update(
        trade_id="contract-exec-order-001",
        client_order_id="contract-exec-order-001",
        risk_approval_id="contract-risk-exec-order",
    )
    execution = request_json(
        "POST",
        "http://localhost:8006/execute",
        execution_payload,
        {
            "X-API-KEY": "dev_execution_key",
            "Idempotency-Key": "contract-exec-order-001",
        },
        expected_status=202,
    )
    execution_data = execution.get("data") or {}
    order = execution_data.get("order") or {}
    job = execution_data.get("execution_job") or {}
    assert order.get("trade_id") == "contract-exec-order-001", execution
    assert order.get("order_id") is not None, execution
    assert job.get("job_id") is not None, execution


def check_analysis_agents() -> None:
    technical = request_json(
        "POST",
        "http://localhost:8002/analyze",
        {"ticker": "AAPL", "timeframe": "1d"},
    )
    technical_data = technical.get("data") or {}
    assert technical_data.get("action") in {"buy", "sell", "hold"}
    assert "confidence_score" in technical_data

    raw_scores = {
        "revenue_3y_cagr": 0.12,
        "revenue_cagr": 0.12,
        "eps_growth": 0.10,
        "fcf_3y_cagr": 0.09,
        "free_cash_flow": 90000000000,
        "operating_cash_flow": 110000000000,
        "roe": 0.35,
        "roa": 0.18,
        "debt_to_equity": 1.2,
        "profit_margins": 0.25,
        "pe_ratio": 28,
        "peg_ratio": 1.8,
        "pb_ratio": 9,
        "market_cap": 3000000000000,
    }
    fundamental = request_json(
        "POST",
        "http://localhost:8001/analyze",
        {
            "ticker": "AAPL",
            "style": "growth",
            "prefetched_data": {
                "ticker": "AAPL",
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "sector": "Technology",
                "metadata": {
                    "sector": "Technology",
                    "exchange": "NASDAQ",
                    "raw_scores": raw_scores,
                    "growth_metrics": {
                        "revenue_3y_cagr": 0.12,
                        "eps_growth": 0.10,
                        "fcf_3y_cagr": 0.09,
                    },
                },
                "raw_scores": raw_scores,
            },
        },
    )
    fundamental_data = fundamental.get("data") or {}
    assert fundamental_data.get("action") in {"buy", "sell", "hold"}
    assert "confidence_score" in fundamental_data

    learning = request_json(
        "POST",
        "http://localhost:8005/learn",
        {
            "account_id": 1,
            "learning_mode": "conservative",
            "window_size": 10,
            "trade_history": [],
            "price_history": {},
            "current_policy": {
                "agent_weights": {"technical": 0.5, "fundamental": 0.5},
                "risk": {
                    "risk_per_trade": 0.01,
                    "max_position_pct": 0.2,
                    "stop_loss_pct": 0.03,
                },
                "strategy_bias": {"preferred_regime": "neutral"},
            },
            "execution_result": {"status": "dry_run"},
        },
    )
    learning_data = learning.get("data") or {}
    assert learning_data.get("learning_state") is not None
    assert "policy_deltas" in learning_data


def check_curator_readiness() -> None:
    health = request_json("GET", "http://localhost:8010/health")
    assert (health.get("data") or {}).get("status") == "healthy", health

    readiness = request_json("GET", "http://localhost:8010/ready")
    readiness_data = readiness.get("data") or {}
    execution = readiness_data.get("execution") or {}
    assert readiness_data.get("ready") is True, readiness
    assert execution.get("mode") == "process", readiness
    assert execution.get("secure_execution_ready") is False, readiness
    assert execution.get("degraded") is True, readiness
    assert execution.get("fallback_enabled") is False, readiness


def check_portfolio_and_profit() -> None:
    portfolio_correlation_id = "agent-contract-e2e-portfolio"
    portfolio = request_json(
        "POST",
        "http://localhost:8012/portfolio/exposure",
        {
            "equity": 100000,
            "cash": 60000,
            "positions": [
                {
                    "symbol": "AAPL",
                    "market_value": 25000,
                    "quantity": 100,
                    "strategy_bucket": "core_dividend",
                    "sector": "Technology",
                },
                {
                    "symbol": "MSFT",
                    "market_value": 15000,
                    "quantity": 50,
                    "strategy_bucket": "value_rebound",
                    "sector": "Technology",
                },
            ],
            "mode": "normal",
        },
        {
            "X-API-KEY": "dev_portfolio_key",
            "X-Correlation-ID": portfolio_correlation_id,
        },
    )
    assert portfolio.get("correlation_id") in {None, portfolio_correlation_id}
    portfolio_data = portfolio.get("data") or {}
    assert "bucket_exposure" in portfolio_data
    assert "position_exposure" in portfolio_data
    assert "rebalance_required" in portfolio_data

    profit_correlation_id = "agent-contract-e2e-profit"
    profit = request_json(
        "POST",
        "http://localhost:8011/profit/plan",
        {
            "schema_version": "profit-decision.v2",
            "position": {
                "symbol": "AAPL",
                "side": "long",
                "quantity": 100,
                "entry_price": 100,
                "current_price": 125,
                "stop_loss": 90,
                "highest_price_since_entry": 130,
                "strategy_bucket": "core_dividend",
            },
        },
        {
            "X-API-KEY": "e2e_profit_contract_key",
            "X-Correlation-ID": profit_correlation_id,
        },
    )
    assert profit.get("schema_version") == "profit-decision.v2"
    assert profit.get("correlation_id") == profit_correlation_id
    profit_data = profit.get("data") or {}
    assert profit_data.get("symbol") == "AAPL"
    assert profit_data.get("primary_action") in {
        "hold",
        "move_stop",
        "partial_exit",
        "exit_all",
        "review",
    }
    assert isinstance(profit_data.get("actions"), list)


def check_manager_dry_run() -> None:
    response = request_json(
        "POST",
        "http://localhost:8000/dry-run/analyze",
        {"ticker": "AAPL", "account_id": 1},
    )
    metadata = response.get("metadata") or {}
    assert metadata.get("dry_run") is True, response
    assert metadata.get("trading_mode") == "PAPER", response


def main() -> int:
    check_risk_database_execution()
    check_analysis_agents()
    check_curator_readiness()
    check_portfolio_and_profit()
    check_manager_dry_run()
    print("Agent Contract E2E checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
