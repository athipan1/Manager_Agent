from decimal import Decimal
from types import SimpleNamespace

from app import portfolio_risk_manager as portfolio


def _scanner_candidate(score: float, *, mode: str = "strategy_aware") -> dict:
    return {
        "metadata": {
            "data_bundle": {
                "opportunity_profile": {
                    "status": "qualified",
                    "opportunity_score": score,
                    "qualification_policy": {
                        "mode": mode,
                        "generic_score": score,
                        "hard_execution_safe": True,
                        "hard_execution_thresholds_relaxed": False,
                    },
                }
            }
        }
    }


def _analysis(score: float, *, mode: str = "strategy_aware") -> dict:
    return {
        "ticker": "ABC",
        "final_verdict": "buy",
        "details": SimpleNamespace(
            technical=SimpleNamespace(score=0.8),
            fundamental=SimpleNamespace(score=0.7),
        ),
        "raw_data": {
            "technical": {
                "data": {
                    "current_price": 100.0,
                    "indicators": {"stop_loss": 95.0},
                }
            }
        },
        "scanner_candidate": _scanner_candidate(score, mode=mode),
    }


def _run(monkeypatch, score: float, *, mode: str = "strategy_aware"):
    captured = {}

    monkeypatch.setattr(portfolio, "build_stock_risk_context", lambda *a, **k: {})

    def fake_assess_trade(**kwargs):
        captured.update(kwargs)
        return {
            "approved": False,
            "action": "buy",
            "position_size": 0,
            "risk_amount": Decimal("0"),
            "entry_price": kwargs["entry_price"],
            "reason": "test capture",
        }

    monkeypatch.setattr(portfolio, "assess_trade", fake_assess_trade)

    decisions = portfolio.assess_portfolio_trades(
        analysis_results=[_analysis(score, mode=mode)],
        cash_balance=Decimal("100000"),
        existing_positions=[],
        per_request_risk_budget=Decimal("0.10"),
        max_total_exposure=Decimal("0.80"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        min_position_value=Decimal("100"),
        open_orders_exposure=Decimal("0"),
        margin_multiplier=Decimal("1"),
        session_risk_context={},
        account_id=1,
        correlation_id="strategy-aware-hourly-test",
    )
    return captured, decisions[0]


def test_hourly_portfolio_risk_uses_half_size_for_065_strategy_aware_candidate(monkeypatch):
    captured, decision = _run(monkeypatch, 0.65)

    assert captured["max_position_pct"] == Decimal("0.100")
    assert captured["stock_risk_context"]["scanner_opportunity_size_multiplier"] == 0.5
    assert decision["scanner_opportunity_size_multiplier"] == 0.5
    assert decision["base_max_position_pct"] == 0.2
    assert decision["effective_max_position_pct"] == 0.1


def test_hourly_portfolio_risk_uses_quarter_size_below_060(monkeypatch):
    captured, decision = _run(monkeypatch, 0.58)

    assert captured["max_position_pct"] == Decimal("0.0500")
    assert decision["scanner_opportunity_size_multiplier"] == 0.25
    assert decision["effective_max_position_pct"] == 0.05


def test_hourly_portfolio_risk_keeps_generic_candidate_at_existing_size(monkeypatch):
    captured, decision = _run(monkeypatch, 0.82, mode="generic")

    assert captured["max_position_pct"] == Decimal("0.20")
    assert decision["scanner_opportunity_size_multiplier"] == 1.0
    assert decision["effective_max_position_pct"] == 0.2
