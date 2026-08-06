from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"Guarded patch expected exactly one match in {relative_path}, found {count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


workflow_path = ".github/workflows/hourly-auto-trading.yml"
replace_once(
    workflow_path,
    """      - name: Record safe no-candidate cycle
        id: no_candidate
        if: steps.scanner_preselection.outputs.backtest_symbols == ''
        working-directory: Manager_Agent
        run: python scripts/record_no_candidate_cycle.py

      - name: Recheck durable emergency halt before broker mutation
        if: steps.preflight.outputs.paper_automation == 'true'
""",
    """      - name: Record safe no-candidate cycle
        id: no_candidate
        if: steps.scanner_preselection.outputs.backtest_symbols == ''
        working-directory: Manager_Agent
        run: python scripts/record_no_candidate_cycle.py

      - name: Resolve controlled no-trade gate
        id: trade_gate
        if: steps.scanner_preselection.outputs.backtest_symbols != ''
        working-directory: Manager_Agent
        run: >-
          python scripts/resolve_hourly_trade_gate.py
          --github-output \"$GITHUB_OUTPUT\"

      - name: Recheck durable emergency halt before broker mutation
        if: >-
          steps.preflight.outputs.paper_automation == 'true' &&
          steps.scanner_preselection.outputs.backtest_symbols != '' &&
          steps.trade_gate.outputs.should_trade == 'true'
""",
)
replace_once(
    workflow_path,
    """      - name: Run Manager candidate, Risk and guarded Execution cycle
        id: trade
        if: steps.scanner_preselection.outputs.backtest_symbols != ''
""",
    """      - name: Run Manager candidate, Risk and guarded Execution cycle
        id: trade
        if: >-
          steps.scanner_preselection.outputs.backtest_symbols != '' &&
          steps.trade_gate.outputs.should_trade == 'true'
""",
)
replace_once(
    workflow_path,
    """      - name: Verify fills, protection and post-execution reconciliation
        id: final_reconciliation
        working-directory: Manager_Agent
""",
    """      - name: Verify fills, protection and post-execution reconciliation
        id: final_reconciliation
        if: ${{ !cancelled() }}
        working-directory: Manager_Agent
""",
)

builder_path = "scripts/build_hourly_operator_artifact.py"
replace_once(
    builder_path,
    """PHASE_STATUSES = {
    \"pending\",
    \"running\",
    \"success\",
    \"warning\",
    \"skipped\",
    \"not_attempted\",
    \"failure\",
    \"cancelled\",
    \"unknown\",
}
""",
    """PHASE_STATUSES = {
    \"pending\",
    \"running\",
    \"success\",
    \"warning\",
    \"skipped\",
    \"not_attempted\",
    \"failure\",
    \"cancelled\",
    \"unknown\",
}
CONTROLLED_NO_TRADE_REASONS = {
    \"market_closed\",
    \"no_eligible_strategy\",
    \"no_preselected_backtest_symbols\",
}
""",
)
replace_once(
    builder_path,
    """    selected = selected_symbols(
        manager_data.get(\"selected_positions\")
        or discovery_data.get(\"selected_positions\")
        or ranked
    )
""",
    """    if \"selected_positions\" in manager_data:
        selected_source = manager_data.get(\"selected_positions\")
    elif \"selected_positions\" in discovery_data:
        selected_source = discovery_data.get(\"selected_positions\")
    else:
        selected_source = ranked
    selected = selected_symbols(selected_source)
""",
)
replace_once(
    builder_path,
    """    execution_reason = execution.get(\"reason\") or (
        \"no_preselected_backtest_symbols\" if not selected else None
    )
    backtest = outcomes.get(\"backtest\")
""",
    """    execution_reason = execution.get(\"reason\") or (
        \"no_preselected_backtest_symbols\" if not selected else None
    )
    execution_attempted = bool_value(candidate.get(\"execute_requested\"))
    candidate_reason = str(
        candidate.get(\"reason\") or execution_reason or \"\"
    ).strip()
    controlled_no_trade = (
        not execution_attempted
        and execution_status == \"not_attempted\"
        and candidate_reason in CONTROLLED_NO_TRADE_REASONS
        and phase_status(outcomes.get(\"risk\")) not in {\"failure\", \"cancelled\"}
        and phase_status(outcomes.get(\"execution\"))
        not in {\"failure\", \"cancelled\"}
    )
    if controlled_no_trade:
        execution_reason = candidate_reason
    backtest = outcomes.get(\"backtest\")
""",
)
replace_once(
    builder_path,
    """    if not selected:
        backtest, risk, execution_phase = \"skipped\", \"skipped\", \"not_attempted\"
    elif execution_status in {\"rejected\", \"risk_rejected\"}:
""",
    """    if controlled_no_trade:
        risk, execution_phase = \"not_attempted\", \"not_attempted\"
        if execution_reason == \"no_preselected_backtest_symbols\":
            backtest = \"skipped\"
    elif not selected:
        backtest, risk, execution_phase = \"skipped\", \"skipped\", \"not_attempted\"
    elif execution_status in {\"rejected\", \"risk_rejected\"}:
""",
)
replace_once(
    builder_path,
    """        phase(
            \"scanner\",
            outcomes.get(\"scanner\"),
            \"No candidate passed the score threshold\" if not selected else None,
        ),
        phase(\"backtest\", backtest, \"No scanner symbols\" if not selected else None),
        phase(\"risk\", risk, \"No candidate\" if not selected else None),
        phase(\"execution\", execution_phase, execution_reason),
        phase(\"final_reconciliation\", outcomes.get(\"final_reconciliation\")),
    ]
    manager_signals = (
""",
    """        phase(
            \"scanner\",
            outcomes.get(\"scanner\"),
            \"No candidate passed the score threshold\"
            if candidate_count == 0
            else None,
        ),
        phase(
            \"backtest\",
            backtest,
            \"No scanner symbols\"
            if candidate_count == 0
            else (
                \"No eligible strategy\"
                if execution_reason == \"no_eligible_strategy\"
                else None
            ),
        ),
        phase(
            \"risk\",
            risk,
            execution_reason
            if controlled_no_trade
            else (\"No candidate\" if not selected else None),
        ),
        phase(\"execution\", execution_phase, execution_reason),
        phase(\"final_reconciliation\", outcomes.get(\"final_reconciliation\")),
    ]
    if controlled_no_trade:
        final_status = phase_status(outcomes.get(\"final_reconciliation\"))
        if final_status == \"success\":
            status = \"controlled_no_trade\"
        elif final_status in {\"failure\", \"cancelled\"}:
            status = final_status
        else:
            status = \"partial\"
    manager_signals = (
""",
)
replace_once(
    builder_path,
    """    execution_attempted = bool_value(candidate.get(\"execute_requested\"))
    partial_fill = bool_value(cycle.get(\"partial_fill_detected\"))
""",
    """    broker_orders_submitted = False
    if not controlled_no_trade:
        broker_orders_submitted = bool(
            as_list(execution.get(\"created\"))
            or execution_status
            in {\"submitted\", \"executed\", \"success\", \"filled\", \"partial_fill\"}
        )
    partial_fill = bool_value(cycle.get(\"partial_fill_detected\"))
""",
)
replace_once(
    builder_path,
    """            \"executionStatus\": execution_status,
            \"executionReason\": execution_reason,
            \"partialFillDetected\": partial_fill,
""",
    """            \"executionStatus\": execution_status,
            \"executionReason\": execution_reason,
            \"controlledNoTradeReason\": (
                execution_reason if controlled_no_trade else None
            ),
            \"brokerOrdersSubmitted\": broker_orders_submitted,
            \"partialFillDetected\": partial_fill,
""",
)
replace_once(
    builder_path,
    """                \"execution\": {
                    \"status\": execution_status,
                    \"reason\": execution_reason,
                },
""",
    """                \"execution\": {
                    \"status\": execution_status,
                    \"reason\": execution_reason,
                    \"brokerOrdersSubmitted\": broker_orders_submitted,
                },
""",
)
replace_once(
    builder_path,
    """        \"partial_fill_detected\": partial_fill,
        \"cycle_status\": status,
""",
    """        \"partial_fill_detected\": partial_fill,
        \"broker_orders_submitted\": broker_orders_submitted,
        \"cycle_status\": status,
""",
)

test_path = "tests/test_build_hourly_operator_artifact.py"
replace_once(
    test_path,
    """    assert phase_map[\"backtest\"] == \"skipped\"
    assert phase_map[\"risk\"] == \"skipped\"
    assert phase_map[\"execution\"] == \"not_attempted\"
""",
    """    assert phase_map[\"backtest\"] == \"skipped\"
    assert phase_map[\"risk\"] == \"not_attempted\"
    assert phase_map[\"execution\"] == \"not_attempted\"
    assert artifact[\"cycle\"][\"status\"] == \"controlled_no_trade\"
    assert artifact[\"cycle\"][\"brokerOrdersSubmitted\"] is False
""",
)


for temporary in (
    ROOT / ".github/workflows/apply-controlled-no-trade-fix-once.yml",
    ROOT / "tools/apply_controlled_no_trade_patch.py",
):
    temporary.unlink(missing_ok=True)
