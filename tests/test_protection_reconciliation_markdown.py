from scripts.store_order_review_ticket import render_protection_reconciliation_markdown


def test_render_protection_reconciliation_markdown_surfaces_blocked_symbols_and_safety():
    markdown = render_protection_reconciliation_markdown(
        {
            "status": "success",
            "data": {
                "mode": "reconciliation_preview_only",
                "safety": "read_only_no_orders_submitted_no_orders_cancelled",
                "summary": {
                    "eligible_position_count": 4,
                    "ready_for_manual_review_count": 0,
                    "blocked_count": 4,
                    "orders_submitted": False,
                    "orders_cancelled": False,
                },
                "plans": [
                    {
                        "symbol": "BKNG",
                        "position_qty": "51",
                        "current_status": "unprotected",
                        "preview_status": "blocked_missing_risk_proposal",
                        "reason": "No SL/TP proposal was supplied for this broker position.",
                        "recommended_next_step": "request_protection_plan_from_risk_agent",
                    }
                ],
            },
        }
    )

    assert "# Protection Reconciliation Preview" in markdown
    assert "Eligible Positions: `4`" in markdown
    assert "Blocked: `4`" in markdown
    assert "BKNG" in markdown
    assert "blocked_missing_risk_proposal" in markdown
    assert "Orders Submitted: `False`" in markdown
    assert "does not cancel, replace, or submit broker orders" in markdown
