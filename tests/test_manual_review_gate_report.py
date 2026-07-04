import json

from scripts.render_manual_review_gate_report import append_manual_review_gate_report, render_manual_review_gate


def test_render_manual_review_gate_shows_validated_symbol():
    lines = []
    render_manual_review_gate(
        lines,
        {
            "status": "success",
            "data": {
                "status": "validated",
                "mode": "manual_order_review_gate",
                "safety": "paper_only_validation_no_broker_state_change",
                "approval_valid": True,
                "execution_enabled": False,
                "ticket_id": "order-review-abc123",
                "requested_symbols": ["BKNG"],
                "summary": {
                    "requested_symbol_count": 1,
                    "validated_symbol_count": 1,
                    "blocked_symbol_count": 0,
                    "orders_changed": False,
                },
                "symbols": [
                    {
                        "symbol": "BKNG",
                        "status": "validated_for_manual_review",
                        "valid": True,
                        "qty": "47",
                        "current_stop_order_id": "stop-bkng",
                        "stop_price": 168.19,
                        "take_profit_price": 217.3,
                        "orders_changed": False,
                        "checks": [{"name": "qty_matches", "passed": True, "detail": "qty must match ticket"}],
                    }
                ],
                "global_checks": [{"name": "confirmation_phrase", "passed": True, "detail": "confirmation phrase must match"}],
                "next_step": "review_validated_gate_before_any_separate_paper_workflow",
            },
        },
    )

    output = "\n".join(lines)
    assert "## Broker Manual Review Gate" in output
    assert "Approval Valid: `True`" in output
    assert "Execution Enabled: `False`" in output
    assert "Orders Changed By Gate: `False`" in output
    assert "BKNG" in output
    assert "validated_for_manual_review" in output
    assert "stop-bkng" in output
    assert "paper-only validation" in output


def test_render_manual_review_gate_shows_blocked_checks():
    lines = []
    render_manual_review_gate(
        lines,
        {
            "status": "success",
            "data": {
                "status": "blocked",
                "mode": "manual_order_review_gate",
                "safety": "paper_only_validation_no_broker_state_change",
                "approval_valid": False,
                "execution_enabled": False,
                "ticket_id": "order-review-abc123",
                "requested_symbols": ["BKNG"],
                "summary": {"validated_symbol_count": 0, "blocked_symbol_count": 1, "orders_changed": False},
                "symbols": [
                    {
                        "symbol": "BKNG",
                        "status": "blocked_validation_failed",
                        "valid": False,
                        "orders_changed": False,
                        "checks": [{"name": "stop_price_matches", "passed": False, "detail": "stop price must match ticket"}],
                    }
                ],
                "global_checks": [{"name": "confirmation_phrase", "passed": False, "detail": "confirmation phrase must match"}],
                "next_step": "fix_blocked_checks_and_regenerate_ticket",
            },
        },
    )

    output = "\n".join(lines)
    assert "Status: `blocked`" in output
    assert "Manual Review Gate Attention Required" in output
    assert "confirmation_phrase" in output
    assert "BKNG.stop_price_matches" in output


def test_append_manual_review_gate_report_appends_section(tmp_path):
    report_path = tmp_path / "hourly-auto-trading-report.json"
    markdown_path = tmp_path / "hourly-auto-trading-report.md"
    markdown_path.write_text("# report\n", encoding="utf-8")
    report_path.write_text(
        json.dumps(
            {
                "manual_review_gate": {
                    "status": "success",
                    "data": {
                        "status": "validated",
                        "mode": "manual_order_review_gate",
                        "safety": "paper_only_validation_no_broker_state_change",
                        "approval_valid": True,
                        "execution_enabled": False,
                        "ticket_id": "order-review-abc123",
                        "requested_symbols": ["BKNG"],
                        "summary": {"validated_symbol_count": 1, "blocked_symbol_count": 0, "orders_changed": False},
                        "symbols": [],
                        "global_checks": [],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    append_manual_review_gate_report(report_path, markdown_path)

    output = markdown_path.read_text(encoding="utf-8")
    assert "# report" in output
    assert "Broker Manual Review Gate" in output
    assert "order-review-abc123" in output
