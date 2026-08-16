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


def test_recorded_pnl_alignment_is_not_ai_profit_without_provenance():
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
    assert evidence["system_evidence"]["system_provenance_verified"] is False
    assert evidence["attribution"]["status"] == (
        "recorded_trade_pnl_aligned_provenance_unverified"
    )
    assert evidence["attribution"]["recorded_trade_pnl_consistent"] is True
    assert evidence["attribution"]["system_profit_proven"] is False


def test_verified_system_managed_pnl_can_prove_positive_system_profit():
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
                "system_provenance_verified": True,
                "system_managed_trades_today": 2,
                "system_managed_realized_pnl": 250,
                "system_provenance_source": "database_managed_fills.v1",
            }
        },
    )

    assert evidence["system_evidence"]["system_provenance_verified"] is True
    assert evidence["system_evidence"]["system_managed_trades_today"] == 2
    assert evidence["system_evidence"]["system_managed_realized_pnl"] == 250.0
    assert evidence["attribution"]["status"] == (
        "system_managed_realized_pnl_aligned"
    )
    assert evidence["attribution"]["provenance_verified"] is True
    assert evidence["attribution"]["system_profit_proven"] is True


def test_incomplete_provenance_claim_fails_closed():
    evidence = build_profit_evidence(
        account=_account(equity="101250", last_equity="101000"),
        position_review={
            "performance_session_risk": {
                "daily_realized_pnl": 250,
                "trades_today": 2,
                "system_provenance_verified": True,
                "system_managed_trades_today": 2,
                # Missing system_managed_realized_pnl means provenance evidence is incomplete.
            }
        },
    )

    assert evidence["system_evidence"]["system_provenance_verified"] is False
    assert evidence["attribution"]["system_profit_proven"] is False


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

    assert evidence["schema_version"] == "paper-profit-evidence.v1.1"
    assert evidence["baseline"]["configured"] is True
    assert evidence["baseline"]["cumulative_equity_change"] == 3248.01
    assert evidence["baseline"]["cumulative_return_pct"] == 3.248
    assert evidence["baseline"]["attribution_status"] == (
        "unproven_without_cash_flow_ledger"
    )
    assert evidence["safety"][
        "explicit_system_provenance_required_for_profit_claim"
    ] is True
    markdown = render_markdown(evidence)
    assert "System provenance verified: `False`" in markdown
    assert "System profit proven: `False`" in markdown
    assert "Baseline attribution remains unproven" in markdown
