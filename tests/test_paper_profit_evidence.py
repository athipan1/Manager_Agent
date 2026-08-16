from decimal import Decimal

from scripts.build_paper_profit_evidence import build_profit_evidence, render_markdown


def _account(*, equity="103248.01", last_equity="103248.01"):
    return {
        "id": "paper-account-secret-id",
        "status": "ACTIVE",
        "equity": equity,
        "last_equity": last_equity,
        "cash": "103248.01",
        "portfolio_value": equity,
        "buying_power": "412992.04",
    }


def test_flat_account_does_not_claim_system_profit():
    evidence = build_profit_evidence(
        account=_account(),
        hourly_report={
            "cycle_status": "controlled_no_trade",
            "broker_orders_submitted": False,
            "positions": [],
            "openOrders": [],
        },
        position_review={
            "performance_session_risk": {
                "daily_realized_pnl": 0,
                "weekly_realized_pnl": 0,
                "trades_today": 0,
                "source": "performance_agent",
            }
        },
    )

    assert evidence["broker"]["day_equity_change"] == 0.0
    assert evidence["attribution"]["status"] == "flat"
    assert evidence["attribution"]["system_profit_proven"] is False
    assert evidence["safety"]["broker_mutation_performed"] is False
    assert evidence["account_ref"] != "paper-account-secret-id"


def test_realized_pnl_alignment_can_prove_positive_system_profit():
    evidence = build_profit_evidence(
        account=_account(equity="101250", last_equity="101000"),
        hourly_report={
            "cycle_status": "traded",
            "broker_orders_submitted": True,
            "positions": [],
            "openOrders": [],
        },
        position_review={
            "performance_session_risk": {
                "daily_realized_pnl": 250,
                "weekly_realized_pnl": 300,
                "trades_today": 2,
                "source": "performance_agent",
            }
        },
    )

    assert evidence["broker"]["day_equity_change"] == 250.0
    assert evidence["system_evidence"]["trades_today"] == 2
    assert evidence["attribution"]["status"] == "system_realized_pnl_aligned"
    assert evidence["attribution"]["system_profit_proven"] is True


def test_equity_change_without_system_evidence_is_not_attributed():
    evidence = build_profit_evidence(
        account=_account(equity="103300", last_equity="103000"),
        hourly_report={
            "cycle_status": "controlled_no_trade",
            "broker_orders_submitted": False,
            "positions": [],
            "openOrders": [],
        },
        position_review={},
    )

    assert evidence["attribution"]["status"] == "unattributed_equity_change"
    assert evidence["attribution"]["confidence"] == "high"
    assert evidence["attribution"]["system_profit_proven"] is False


def test_baseline_reports_change_but_does_not_overclaim_attribution():
    evidence = build_profit_evidence(
        account=_account(),
        baseline_equity=Decimal("100000"),
    )

    assert evidence["baseline"]["configured"] is True
    assert evidence["baseline"]["cumulative_equity_change"] == 3248.01
    assert evidence["baseline"]["cumulative_return_pct"] == 3.248
    assert evidence["baseline"]["attribution_status"] == (
        "unproven_without_cash_flow_ledger"
    )
    markdown = render_markdown(evidence)
    assert "System profit proven: `False`" in markdown
    assert "Baseline attribution remains unproven" in markdown
