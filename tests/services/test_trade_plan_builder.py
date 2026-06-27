from decimal import Decimal

from app.contracts import ReportDetail, ReportDetails
from app.services.trade_plan_builder import attach_trade_plan_to_decision, build_trade_plan


def _analysis_result():
    return {
        "ticker": "AAPL",
        "final_verdict": "buy",
        "status": "complete",
        "details": ReportDetails(
            technical=ReportDetail(action="buy", score=0.70, reason="technical setup"),
            fundamental=ReportDetail(action="buy", score=0.60, reason="fundamental setup"),
        ),
        "raw_data": {
            "technical": {
                "status": "success",
                "data": {
                    "current_price": 100,
                    "indicators": {"stop_loss": 95},
                },
            },
            "fundamental": {"status": "success", "data": {}},
        },
    }


def test_build_trade_plan_from_approved_decision():
    decision = {
        "approved": True,
        "reason": "Approved by Risk_Agent",
        "symbol": "AAPL",
        "action": "buy",
        "entry_price": Decimal("100"),
        "position_size": 10,
        "final_quantity": 10,
        "stop_loss": Decimal("95"),
        "risk_amount": Decimal("50"),
        "risk_approval_id": "risk-abc",
        "stock_risk_context": {"strategy_bucket": "value_rebound"},
        "session_risk_context": {"trades_today": 1},
    }

    plan = build_trade_plan(
        analysis_result=_analysis_result(),
        trade_decision=decision,
        account_id=1,
        correlation_id="corr-1",
        dry_run=True,
    )

    assert plan.plan_id == "risk-abc"
    assert plan.symbol == "AAPL"
    assert plan.status == "risk_approved"
    assert plan.side == "buy"
    assert plan.quantity == 10
    assert plan.final_quantity == 10
    assert plan.exit.stop_loss == 95
    assert plan.risk.max_loss_amount == 50
    assert plan.strategy_bucket == "value_rebound"
    assert plan.confidence_score == 0.65
    assert plan.risk_approval_id == "risk-abc"
    assert plan.dry_run is True


def test_attach_trade_plan_to_decision_adds_snapshot_and_id():
    decision = {
        "approved": False,
        "reason": "Rejected by daily loss guard",
        "symbol": "AAPL",
        "action": "buy",
        "entry_price": 100,
        "position_size": 0,
        "stop_loss": 95,
    }

    plan = attach_trade_plan_to_decision(
        analysis_result=_analysis_result(),
        trade_decision=decision,
        account_id="1",
        correlation_id="corr-2",
        dry_run=False,
    )

    assert plan is not None
    assert decision["trade_plan_id"] == "plan-corr-2-AAPL"
    assert decision["trade_plan"]["status"] == "rejected"
    assert decision["trade_plan"]["reasons"] == ["Rejected by daily loss guard"]


def test_attach_trade_plan_is_non_blocking_on_invalid_plan():
    decision = {
        "approved": True,
        "symbol": "AAPL",
        "action": "buy",
        "entry_price": 100,
        "position_size": 10,
        "stop_loss": 101,
    }

    plan = attach_trade_plan_to_decision(
        analysis_result=_analysis_result(),
        trade_decision=decision,
        account_id="1",
        correlation_id="corr-3",
    )

    assert plan is None
    assert "buy trade stop_loss" in decision["trade_plan_error"]
