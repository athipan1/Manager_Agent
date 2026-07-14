import argparse
import json

from scripts import store_order_review_ticket as module


def failed_report():
    return {
        "generated_at": "2026-07-14T17:48:30+00:00",
        "flow": "discover_analyze_trade",
        "response": {
            "status": "error",
            "http_status": 500,
            "body": json.dumps(
                {"detail": "Agent technical-agent returned error status: price history missing"}
            ),
        },
        "order_review_approval_ticket": {
            "status": "success",
            "data": {"ticket_id": "misleading-empty-ticket"},
        },
    }


def test_manager_flow_failure_extracts_nested_http_detail():
    reason = module.manager_flow_failure(failed_report())

    assert reason == (
        "Manager discover-analyze-trade failed (HTTP 500): "
        "Agent technical-agent returned error status: price history missing"
    )


def test_main_fails_before_storing_misleading_ticket(monkeypatch, tmp_path):
    input_path = tmp_path / "hourly-auto-trading-report.json"
    output_path = tmp_path / "order-review-ticket-store-result.json"
    input_path.write_text(json.dumps(failed_report()), encoding="utf-8")
    args = argparse.Namespace(
        database_url="http://database-agent:8004",
        database_api_key="test-key",
        account_id="1",
        source="manager-agent-hourly-workflow",
        input_json=input_path,
        output_json=output_path,
    )
    monkeypatch.setattr(module, "parse_args", lambda: args)

    def should_not_store(*args, **kwargs):
        raise AssertionError("failed Manager flow must not persist an order-review ticket")

    monkeypatch.setattr(module, "store_order_review_ticket", should_not_store)

    assert module.main() == 1

    validation = json.loads(output_path.read_text(encoding="utf-8"))
    updated_report = json.loads(input_path.read_text(encoding="utf-8"))
    assert validation["status"] == "error"
    assert validation["stage"] == "discover_analyze_trade"
    assert validation["store_skipped"] is True
    assert "HTTP 500" in validation["reason"]
    assert updated_report["workflow_validation"] == validation
