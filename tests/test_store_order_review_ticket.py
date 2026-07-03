from scripts.store_order_review_ticket import (
    attach_audit_to_report,
    build_payload,
    render_audit_summary_markdown,
    store_order_review_ticket,
    ticket_from_report,
)


def sample_report():
    return {
        "generated_at": "2026-07-03T16:46:36+00:00",
        "mode": "ALPACA_PAPER",
        "broker_mode": "ALPACA",
        "flow": "discover_analyze_trade",
        "order_review_approval_ticket": {
            "status": "success",
            "data": {
                "ticket_id": "order-review-abc123",
                "mode": "manual_approval_ticket",
                "safety": "read_only_no_orders_submitted_no_orders_cancelled",
                "approval_required": True,
                "execution_enabled": False,
                "manual_confirmation_phrase": "APPROVE_ORDER_REVIEW_TICKET",
                "requested_symbols": ["ACGL", "ADBE"],
                "summary": {
                    "ready_for_manual_approval_count": 2,
                    "blocked_count": 0,
                    "orders_submitted": False,
                    "orders_cancelled": False,
                },
                "ready_for_manual_approval": [
                    {"symbol": "ACGL", "position_qty": "82"},
                    {"symbol": "ADBE", "position_qty": "52"},
                ],
            },
        },
    }


def sample_audit_summary_response():
    return {
        "status": "success",
        "data": {
            "total_count": 3,
            "ready_ticket_count": 2,
            "blocked_ticket_count": 1,
            "approval_required_count": 3,
            "execution_enabled_count": 0,
            "total_ready_items": 6,
            "total_blocked_items": 1,
            "latest_ticket": {
                "ticket_id": "order-review-abc123",
                "status": "ready_for_manual_approval",
                "ready_count": 2,
                "blocked_count": 0,
                "approval_required": True,
                "execution_enabled": False,
                "created_at": "2026-07-03T16:46:36Z",
                "updated_at": "2026-07-03T16:46:36Z",
            },
        },
    }


def test_ticket_from_report_unwraps_execution_response():
    ticket = ticket_from_report(sample_report())

    assert ticket["ticket_id"] == "order-review-abc123"
    assert ticket["execution_enabled"] is False


def test_build_payload_maps_ticket_summary_and_safety_fields():
    payload = build_payload(sample_report(), account_id=1)

    assert payload["ticket_id"] == "order-review-abc123"
    assert payload["account_id"] == 1
    assert payload["source"] == "manager-agent-hourly-workflow"
    assert payload["mode"] == "manual_approval_ticket"
    assert payload["safety"] == "read_only_no_orders_submitted_no_orders_cancelled"
    assert payload["status"] == "ready_for_manual_approval"
    assert payload["approval_required"] is True
    assert payload["execution_enabled"] is False
    assert payload["manual_confirmation_phrase"] == "APPROVE_ORDER_REVIEW_TICKET"
    assert payload["requested_symbols"] == ["ACGL", "ADBE"]
    assert payload["ready_count"] == 2
    assert payload["blocked_count"] == 0
    assert payload["orders_submitted"] is False
    assert payload["orders_cancelled"] is False
    assert payload["ticket_payload"]["data"]["ticket_id"] == "order-review-abc123"
    assert payload["metadata"]["workflow"] == "hourly-auto-trading"


def test_build_payload_marks_blocked_status_when_ticket_has_blocked_items():
    report = sample_report()
    report["order_review_approval_ticket"]["data"]["summary"]["ready_for_manual_approval_count"] = 0
    report["order_review_approval_ticket"]["data"]["summary"]["blocked_count"] = 1

    payload = build_payload(report, account_id="paper-1")

    assert payload["account_id"] == "paper-1"
    assert payload["status"] == "blocked"
    assert payload["ready_count"] == 0
    assert payload["blocked_count"] == 1


def test_store_order_review_ticket_posts_to_database_and_fetches_summary(monkeypatch):
    post_calls = []
    get_calls = []

    def fake_post_json(base_url, path, payload, api_key=None):
        post_calls.append((base_url, path, payload, api_key))
        return {"status": "success", "data": {"ticket_id": payload["ticket_id"]}}

    def fake_get_json(base_url, path, params=None, api_key=None):
        get_calls.append((base_url, path, params, api_key))
        return sample_audit_summary_response()

    monkeypatch.setattr("scripts.store_order_review_ticket.post_json", fake_post_json)
    monkeypatch.setattr("scripts.store_order_review_ticket.get_json", fake_get_json)

    result = store_order_review_ticket(sample_report(), "http://database-agent:8004", "test-key", account_id=1)

    assert post_calls[0][0] == "http://database-agent:8004"
    assert post_calls[0][1] == "/order-review-tickets"
    assert post_calls[0][3] == "test-key"
    assert post_calls[0][2]["ticket_id"] == "order-review-abc123"
    assert get_calls[0][1] == "/order-review-tickets/summary"
    assert get_calls[0][2]["latest_ticket_id"] == "order-review-abc123"
    assert result["response"]["status"] == "success"
    assert result["audit_summary"]["status"] == "success"


def test_attach_audit_to_report_adds_store_result_and_summary():
    store_result = {"response": {"status": "success"}, "audit_summary": sample_audit_summary_response()}

    updated = attach_audit_to_report(sample_report(), store_result)

    assert updated["order_review_ticket_store_result"] == store_result
    assert updated["order_review_ticket_audit_summary"]["data"]["total_count"] == 3


def test_render_audit_summary_markdown_includes_latest_ticket_and_counts():
    markdown = render_audit_summary_markdown(
        sample_audit_summary_response(),
        {"response": {"status": "success"}},
    )

    assert "# Order Review Ticket Audit Summary" in markdown
    assert "Store Status: `success`" in markdown
    assert "Total Tickets: `3`" in markdown
    assert "Ticket ID: `order-review-abc123`" in markdown
    assert "Execution Enabled: `False`" in markdown
