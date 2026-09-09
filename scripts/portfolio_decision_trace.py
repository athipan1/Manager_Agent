"""Join recorded Portfolio and broker evidence without granting authority."""
from __future__ import annotations

try:
    from .build_selection_funnel import obj, rows, number
except ImportError:
    from build_selection_funnel import obj, rows, number


def indexed(value):
    return {str(r.get("symbol") or "").upper(): r for r in rows(value) if isinstance(r, dict)}


def enrich_portfolio_rows(result, data, cycle, final_cycle):
    cycle_id = data.get("report_id")
    actual = obj(obj(cycle.get("manager_response")).get("data"))
    actual_same_cycle = bool(cycle_id) and actual.get("report_id") == cycle_id
    execution = obj(actual.get("execution")) if actual_same_cycle else {}
    risk = indexed(actual.get("risk_approvals")) if actual_same_cycle else {}
    authorizations = indexed(execution.get("authorized_orders"))
    created = indexed(execution.get("created"))
    ranked = indexed(data.get("ranked_candidates"))
    selected = indexed(data.get("pre_gate_selected_positions"))
    plan = obj(data.get("allocation_plan"))
    capacity = obj(data.get("pre_risk_capacity"))
    capacities = indexed(capacity.get("diagnostics"))
    exposures = indexed(obj(data.get("exposure_gate")).get("decisions"))
    liquidity = indexed(obj(plan.get("investability_gate")).get("decisions"))
    history = indexed(obj(data.get("pre_backtest_history_gate")).get("evaluations"))
    evaluations = indexed(obj(data.get("bucket_selection")).get("selection_evaluations"))
    classification_min = number(plan.get("auto_classify_threshold"))
    equity = number(plan.get("portfolio_value"))
    final_same_cycle = bool(cycle_id) and obj(final_cycle.get("review")).get("portfolio_cycle_id") == cycle_id
    receipts = rows(final_cycle.get("submitted_order_statuses")) if final_same_cycle else []
    for row in result:
        symbol = row["symbol"]
        candidate, position = ranked.get(symbol, {}), selected.get(symbol, {})
        bucket = candidate.get("strategy_bucket")
        policy = obj(obj(plan.get("buckets")).get(bucket))
        confidence = number(candidate.get("bucket_confidence"))
        bucket_min = number(policy.get("min_final_score"))
        score = row["final_score"]
        bucket_known = bool(candidate) and classification_min is not None
        row["bucket_pass"] = (bool(
            policy and candidate.get("bucket_classification_status") == "classified"
            and candidate.get("allows_new_entry") is True
            and candidate.get("evidence_gate_passed") is True
            and confidence is not None and confidence >= classification_min
            and bucket_min is not None and score is not None and score >= bucket_min
        ) if bucket_known else None)
        amount = number(position.get("target_value"))
        weight = amount / equity if amount is not None and equity is not None and equity > 0 else (0.0 if "pre_gate_selected_positions" in data else None)
        row.update(bucket=bucket, bucket_eligibility=row["bucket_pass"], allocation_weight=weight)
        evidence = obj(candidate.get("evidence_summary"))
        row["allocation"].update(
            bucket_min_final_score=bucket_min, classification_min_confidence=classification_min,
            allocation_weight=weight, allocated_value=amount, portfolio_value=equity,
            bucket_target_weight=policy.get("target_weight"),
            selection_evaluation=evaluations.get(symbol),
            classification_reasons=candidate.get("bucket_classification_reasons"),
            classification_rule_trace=evidence.get("classification_rule_trace"),
            classification_policy_adjustments=evidence.get("classification_policy_adjustments"),
            source_evidence=evidence,
        )
        row["constraints"] = {
            "capacity": capacities.get(symbol) or {"status": "not_evaluated"},
            "capacity_policy": capacity.get("policy"),
            "exposure": exposures.get(symbol) or {"status": "not_evaluated"},
            "liquidity": liquidity.get(symbol) or {"status": "not_evaluated_or_unavailable"},
            "correlation": {"status": "not_recorded", "passed": None},
            "cash": {"status": "see_risk_and_batch_validation", "passed": None},
        }
        admission = history.get(symbol)
        if admission:
            row["backtest_history_admission"] = admission
            if admission.get("history_eligible") is False and row["backtest"] is None:
                row["backtest_pass"] = False
        row["backtest_status"] = (
            "passed" if row["backtest_pass"] is True else
            "not_run_insufficient_history" if admission and admission.get("history_eligible") is False and row["backtest"] is None else
            "rejected" if row["backtest_pass"] is False else "not_evaluated_or_unavailable"
        )
        approval = risk.get(symbol, {})
        row["risk_pass"] = approval.get("approved") if isinstance(approval.get("approved"), bool) else None
        row["risk"] = approval or {"status": "not_evaluated"}
        row["risk_status"] = "approved" if row["risk_pass"] is True else "rejected" if row["risk_pass"] is False else "not_evaluated"
        auth = authorizations.get(symbol, {})
        risk_data = obj(obj(approval.get("risk_agent_response")).get("data"))
        approval_id = approval.get("risk_approval_id") or risk_data.get("risk_approval_id") or risk_data.get("approval_id")
        row["execution_authorized"] = bool(
            actual_same_cycle and cycle.get("execute_requested") is True
            and auth.get("portfolio_cycle_id") == cycle_id
            and approval_id and auth.get("risk_approval_id") == approval_id
            and obj(execution.get("validation")).get("approved") is True
            and all(row.get(g) is True for g in ("scanner_pass", "score_pass", "verdict_pass", "bucket_pass", "allocation_pass", "backtest_pass", "risk_pass"))
            and row["allocation"].get("exposure_allowed") is True
        )
        internal = created.get(symbol, {})
        internal_id = internal.get("order_id")
        matched = [r for r in receipts if isinstance(r, dict) and internal_id is not None
                   and str(r.get("order_id")) == str(internal_id)
                   and str(r.get("symbol") or "").upper() == symbol and r.get("broker_order_id")]
        row["broker_order"] = bool(matched)
        row["execution"].update(
            authorization=auth or None, same_cycle=actual_same_cycle,
            final_reconciliation_same_cycle=final_same_cycle,
            created_order_record=bool(internal), broker_receipts=matched,
            post_execution_reconciliation=final_cycle.get("post_execution_reconciliation") if final_same_cycle else None,
            batch_validation=execution.get("validation"),
            contract_issues=["BROKER_ORDER_WITHOUT_MATCHING_AUTHORIZATION"] if matched and not row["execution_authorized"] else [],
        )
        if row["risk_pass"] is False:
            row["rejections"].append({"symbol": symbol, "gate": "risk", "reason_code": "RISK_REJECTED", "reason": approval.get("reason") or "Risk rejected the candidate; see risk response.", "evidence": approval})
        for failure in rows(execution.get("failed")) + rows(execution.get("failed_to_build")) + rows(execution.get("duplicate_orders")) + rows(execution.get("skipped_open_order_conflicts")):
            if failure.get("symbol") == symbol:
                row["rejections"].append({"symbol": symbol, "gate": "execution", "reason_code": failure.get("code") or failure.get("status") or "EXECUTION_REJECTED", "reason": failure.get("reason") or failure.get("error") or "See execution evidence.", "evidence": failure})
        row["rejection_codes"] = sorted({r["reason_code"] for r in row["rejections"]})
        row["stage_status"].update({g: "passed" if row[g] is True else "failed" if row[g] is False else "not_evaluated_or_unavailable" for g in ("bucket_pass", "backtest_pass", "risk_pass", "execution_authorized", "broker_order")})
