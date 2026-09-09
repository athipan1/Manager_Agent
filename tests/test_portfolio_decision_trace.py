"""Diagnostic joins only: these fixtures never submit an order."""
from copy import deepcopy

from scripts.portfolio_decision_trace import enrich_portfolio_rows


def evidence():
    row = {"symbol": "TEST", "final_score": .8, "scanner_pass": True,
           "score_pass": True, "verdict_pass": True, "allocation_pass": True,
           "backtest_pass": True, "backtest": {}, "allocation": {"exposure_allowed": True},
           "execution": {}, "rejections": [], "stage_status": {}}
    data = {"report_id": "cycle", "ranked_candidates": [{"symbol": "TEST",
            "strategy_bucket": "value_rebound", "bucket_confidence": .8,
            "bucket_classification_status": "classified", "allows_new_entry": True,
            "evidence_gate_passed": True}],
            "pre_gate_selected_positions": [{"symbol": "TEST", "target_value": 7000, "target_weight": .3}],
            "allocation_plan": {"auto_classify_threshold": .7, "portfolio_value": 100000,
                "buckets": {"value_rebound": {"min_final_score": .58, "target_weight": .3}}}}
    cycle = {"execute_requested": True, "manager_response": {"data": {
        "report_id": "cycle", "risk_approvals": [{"symbol": "TEST", "approved": True, "risk_approval_id": "risk-test"}],
        "execution": {"validation": {"approved": True},
            "authorized_orders": [{"symbol": "TEST", "portfolio_cycle_id": "cycle", "risk_approval_id": "risk-test"}],
            "created": [{"symbol": "TEST", "order_id": "internal-1"}]}}}}
    final = {"review": {"portfolio_cycle_id": "cycle"}, "submitted_order_statuses": [
        {"symbol": "TEST", "order_id": "internal-1", "broker_order_id": "broker-1", "status": "placed"}]}
    return row, data, cycle, final


def test_authorization_and_broker_receipt_are_separate_and_weight_is_per_symbol():
    row, data, cycle, final = evidence()
    enrich_portfolio_rows([row], data, cycle, {})
    assert row["execution_authorized"] is True
    assert row["broker_order"] is False  # An internal record is not an Alpaca receipt.
    assert row["allocation_weight"] == .07 and row["allocation"]["bucket_target_weight"] == .3
    enrich_portfolio_rows([row], data, cycle, final)
    assert row["broker_order"] is True


def test_stale_risk_or_authorization_cannot_authorize_current_cycle():
    row, data, cycle, final = evidence()
    cycle["manager_response"]["data"]["report_id"] = "old-cycle"
    enrich_portfolio_rows([row], data, cycle, final)
    assert row["risk_pass"] is None and not row["execution_authorized"]
    assert not row["broker_order"]


def test_mismatched_risk_id_is_not_authority_even_with_actual_broker_receipt():
    row, data, cycle, final = evidence()
    cycle["manager_response"]["data"]["execution"]["authorized_orders"][0]["risk_approval_id"] = "other"
    enrich_portfolio_rows([row], data, cycle, final)
    assert not row["execution_authorized"] and row["broker_order"]
    assert row["execution"]["contract_issues"] == ["BROKER_ORDER_WITHOUT_MATCHING_AUTHORIZATION"]


def test_hold_and_bucket_score_rejections_remain_independent():
    row, data, cycle, final = evidence()
    row["verdict_pass"] = False
    enrich_portfolio_rows([row], data, cycle, {})
    assert row["bucket_pass"] is True and not row["execution_authorized"]
    row["final_score"] = .57  # Global .55 passes; value bucket .58 does not.
    enrich_portfolio_rows([row], data, cycle, {})
    assert row["bucket_pass"] is False and row["score_pass"] is True


def test_insufficient_history_records_backtest_failure_without_invented_metrics():
    row, data, cycle, final = evidence()
    row.update(backtest=None, backtest_pass=None)
    data["pre_backtest_history_gate"] = {"evaluations": [{"symbol": "TEST", "history_eligible": False,
                                                         "bars_observed": 341, "bars_required": 882}]}
    enrich_portfolio_rows([row], data, {}, {})
    assert row["backtest_pass"] is False and row["backtest"] is None
    assert row["backtest_status"] == "not_run_insufficient_history"
    assert row["risk_status"] == "not_evaluated" and not row["execution_authorized"]


def test_receipts_from_other_cycle_or_other_internal_order_do_not_count():
    row, data, cycle, final = evidence()
    wrong_cycle = deepcopy(final)
    wrong_cycle["review"]["portfolio_cycle_id"] = "old"
    enrich_portfolio_rows([row], data, cycle, wrong_cycle)
    assert not row["broker_order"]
    final["submitted_order_statuses"][0]["order_id"] = "other-internal"
    enrich_portfolio_rows([row], data, cycle, final)
    assert not row["broker_order"]
