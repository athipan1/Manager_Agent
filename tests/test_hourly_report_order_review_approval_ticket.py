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
                "approval_required": True,
                "execution_enabled": False,
                "manual_confirmation_phrase": "APPROVE_ORDER_REVIEW_TICKET",
                "requested_symbols": ["ACGL"],
                "summary": {
                    "requested_symbol_count": 1,
                    "ready_for_manual_approval_count": 1,
                    "blocked_count": 0,
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
                "blocked": [],
            },
        },
    )

    output = "\n".join(lines)
    assert "## Broker Order Review Approval Ticket" in output
    assert "Ticket ID: `order-review-abc123`" in output
    assert "Execution Enabled: `False`" in output
    assert "APPROVE_ORDER_REVIEW_TICKET" in output
    assert "ACGL" in output
    assert "stop-123" in output
    assert "92.94" in output
    assert "120.72" in output
    assert "manual_approval_required" in output
    assert "read-only/manual-approval" in output


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
                "summary": {
                    "ready_for_manual_approval_count": 0,
                    "blocked_count": 1,
                    "orders_submitted": False,
                    "orders_cancelled": False,
                },
                "ready_for_manual_approval": [],
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
    assert "Blocked: `1`" in output
    assert "Blocked Approval Ticket Items" in output
    assert "MSFT" in output
    assert "blocked_symbol_not_found_in_preview" in output
    assert "refresh_preview_or_verify_current_broker_positions" in output


def test_render_order_review_approval_ticket_ignores_empty_payload():
    lines = []
    render_order_review_approval_ticket(lines, {})

    assert lines == []
