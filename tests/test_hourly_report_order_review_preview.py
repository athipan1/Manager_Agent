from scripts.render_hourly_portfolio_report import render_order_review_preview


def test_render_order_review_preview_shows_blocked_preview_status():
    lines = []
    render_order_review_preview(
        lines,
        {
            "status": "success",
            "data": {
                "mode": "preview_only",
                "safety": "read_only_no_orders_submitted_no_orders_cancelled",
                "reward_risk_ratio": 2.0,
                "summary": {
                    "candidate_count": 1,
                    "ready_for_manual_review_count": 0,
                    "blocked_count": 1,
                    "no_action_count": 0,
                    "orders_submitted": False,
                    "orders_cancelled": False,
                },
                "plans": [
                    {
                        "symbol": "ACGL",
                        "position_qty": "82",
                        "preview_status": "blocked_missing_stop_price",
                        "recommended_next_step": "fetch_full_broker_order_details_before_cancel_replace",
                        "orders_submitted": False,
                        "orders_cancelled": False,
                        "proposed_actions": [],
                    }
                ],
            },
        },
    )

    output = "\n".join(lines)
    assert "## Broker Order Review Preview" in output
    assert "Mode: `preview_only`" in output
    assert "Blocked: `1`" in output
    assert "Orders Submitted By Preview: `False`" in output
    assert "Orders Cancelled By Preview: `False`" in output
    assert "ACGL" in output
    assert "blocked_missing_stop_price" in output
    assert "fetch_full_broker_order_details_before_cancel_replace" in output
    assert "preview-only" in output


def test_render_order_review_preview_shows_ready_for_manual_review_plan():
    lines = []
    render_order_review_preview(
        lines,
        {
            "status": "success",
            "data": {
                "mode": "preview_only",
                "safety": "read_only_no_orders_submitted_no_orders_cancelled",
                "reward_risk_ratio": 2.0,
                "summary": {
                    "candidate_count": 1,
                    "ready_for_manual_review_count": 1,
                    "blocked_count": 0,
                    "no_action_count": 0,
                    "orders_submitted": False,
                    "orders_cancelled": False,
                },
                "plans": [
                    {
                        "symbol": "ADBE",
                        "position_qty": "52",
                        "preview_status": "ready_for_manual_review",
                        "stop_price": 200.0,
                        "take_profit_price": 260.0,
                        "recommended_next_step": "manual_approval_required_before_execute",
                        "proposed_actions": [
                            {"action": "would_cancel_existing_stop_order"},
                            {"action": "would_submit_bracket_replacement"},
                        ],
                    }
                ],
            },
        },
    )

    output = "\n".join(lines)
    assert "Ready For Manual Review: `1`" in output
    assert "ADBE" in output
    assert "ready_for_manual_review" in output
    assert "200.0" in output
    assert "260.0" in output
    assert "|" in output


def test_render_order_review_preview_ignores_empty_payload():
    lines = []
    render_order_review_preview(lines, {})

    assert lines == []
