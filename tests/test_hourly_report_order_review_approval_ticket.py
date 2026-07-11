from scripts.render_hourly_portfolio_report import render_order_review_approval_ticket


def test_render_order_review_approval_ticket_shows_manual_approval_details():
    lines = []
    render_order_review_approval_ticket(
        lines,
        {
            "status": "success",
            "data": {
                "ticket_id": "order-review-abc123",
                "mode": "manual_approval_ticket",
                "safety": "read_only_no_orders_submitted_no_orders_cancelled",
                "ticket_status": "ready_for_manual_approval",
                "requires_operator_attention": True,
                "approval_required": True,
                "execution_enabled": False,
                "manual_confirmation_phrase": "APPROVE_ORDER_REVIEW_TICKET",
                "requested_symbols": ["ACGL"],
                "next_step": "review_ticket_then_use_a_separate_approved_execution_workflow",
                "summary": {
                    "requested_symbol_count": 1,
                    "ready_for_manual_approval_count": 1,
                    "no_action_required_count": 0,
                    "blocked_count": 0,
                    "requires_operator_attention": True,
                    "orders_submitted": False,
                    "orders_cancelled": False,
                },
                "ready_for_manual_approval": [
                    {
                        "symbol": "ACGL",
                        "position_qty": "82",
                        "current_stop_order_id": "stop-123",
                        "stop_price": "92.94",
                        "take_profit_price": "120.72",
                        "reward_risk_ratio": 2.0,
                        "approval_status": "manual_approval_required",
                        "proposed_actions": [
                            {"action": "would_cancel_existing_stop_order"},
                            {"action": "would_submit_bracket_replacement"},
                        ],
                    }
                ],
                "no_action_required": [],
                "blocked": [],
            },
        },
    )

    output = "\n".join(lines)
    assert "## Broker Order Review Approval Ticket" in output
    assert "Ticket ID: `order-review-abc123`" in output
    assert "Ticket Status: `ready_for_manual_approval`" in output
    assert "Requires Operator Attention: `True`" in output
    assert "Next Step: `review_ticket_then_use_a_separate_approved_execution_workflow`" in output
    assert "Execution Enabled: `False`" in output
    assert "APPROVE_ORDER_REVIEW_TICKET" in output
    assert "ACGL" in output
    assert "stop-123" in output
    assert "92.94" in output
    assert "120.72" in output
    assert "manual_approval_required" in output
    assert "read-only/manual-approval" in output


def test_render_order_review_approval_ticket_shows_no_action_items():
    lines = []
    render_order_review_approval_ticket(
        lines,
        {
            "status": "success",
            "data": {
                "ticket_id": "order-review-clean",
                "mode": "manual_approval_ticket",
                "safety": "read_only_no_orders_submitted_no_orders_cancelled",
                "ticket_status": "no_action_required",
                "requires_operator_attention": False,
                "approval_required": False,
                "execution_enabled": False,
                "next_step": "no_manual_approval_required",
                "summary": {
                    "ready_for_manual_approval_count": 0,
                    "no_action_required_count": 1,
                    "blocked_count": 0,
                    "requires_operator_attention": False,
                },
                "ready_for_manual_approval": [],
                "no_action_required": [
                    {
                        "symbol": "CINF",
                        "preview_status": "no_action_required",
                        "reason": "Existing protection already matches policy.",
                        "recommended_next_step": "keep_current_orders",
                    }
                ],
                "blocked": [],
            },
        },
    )

    output = "\n".join(lines)
    assert "Ticket Status: `no_action_required`" in output
    assert "Requires Operator Attention: `False`" in output
    assert "No Action Required: `1`" in output
    assert "### No Action Required" in output
    assert "CINF" in output
    assert "keep_current_orders" in output
    assert "Next Step: `no_manual_approval_required`" in output
    assert "### No Operator Action Required" in output
    assert "Manual Approval Safety" not in output


def test_render_order_review_approval_ticket_shows_blocked_items():
    lines = []
    render_order_review_approval_ticket(
        lines,
        {
            "status": "success",
            "data": {
                "ticket_id": "order-review-blocked",
                "mode": "manual_approval_ticket",
                "safety": "read_only_no_orders_submitted_no_orders_cancelled",
                "ticket_status": "blocked",
                "requires_operator_attention": True,
                "approval_required": False,
                "next_step": "resolve_blockers_then_refresh_order_review_preview",
                "summary": {
                    "ready_for_manual_approval_count": 0,
                    "no_action_required_count": 0,
                    "blocked_count": 1,
                    "requires_operator_attention": True,
                    "orders_submitted": False,
                    "orders_cancelled": False,
                },
                "ready_for_manual_approval": [],
                "no_action_required": [],
                "blocked": [
                    {
                        "symbol": "MSFT",
                        "preview_status": "blocked_symbol_not_found_in_preview",
                        "reason": "Requested symbol was not present in the latest order review preview.",
                        "recommended_next_step": "refresh_preview_or_verify_current_broker_positions",
                    }
                ],
            },
        },
    )

    output = "\n".join(lines)
    assert "Ticket Status: `blocked`" in output
    assert "Requires Operator Attention: `True`" in output
    assert "Blocked: `1`" in output
    assert "Next Step: `resolve_blockers_then_refresh_order_review_preview`" in output
    assert "Blocked Approval Ticket Items" in output
    assert "Operator Attention Required" in output
    assert "MSFT" in output
    assert "blocked_symbol_not_found_in_preview" in output
    assert "refresh_preview_or_verify_current_broker_positions" in output
    assert "Manual Approval Safety" not in output


def test_render_order_review_approval_ticket_ignores_empty_payload():
    lines = []
    render_order_review_approval_ticket(lines, {})

    assert lines == []
