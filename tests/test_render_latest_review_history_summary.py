from scripts.render_latest_review_history_summary import latest_summary_path, render_markdown, fetch_latest_summary


def sample_result():
    return {
        "request": {"account_id": "1", "bucket": "value_rebound"},
        "response": {"status": "success", "data": sample_summary()},
        "summary": sample_summary(),
    }


def sample_summary():
    return {
        "latest_review_run_id": "bucket-review-value_rebound-20260701",
        "account_id": "1",
        "bucket": "value_rebound",
        "mode": "BUCKET_PROFIT_REVIEW_REPORT_ONLY",
        "status": "completed",
        "generated_at": "2026-07-01T16:26:28Z",
        "positions_seen": 4,
        "reviewed_positions": 2,
        "database_bucket_hints_applied": 3,
        "profit_agent_used": 2,
        "risk_approved": 2,
        "risk_rejected": 0,
        "execution_preview_ready": 2,
        "execution_preview_blocked": 0,
        "execution_submissions": 0,
        "orders_submitted": False,
        "advisory_only": True,
        "final_decisions": {"HOLD": 2},
        "profit_actions": {"hold": 2},
        "risk_statuses": {"approved": 2},
        "preview_statuses": {"ready": 2},
        "decisions": [
            {
                "symbol": "ACGL",
                "profit_action": "hold",
                "risk_status": "approved",
                "preview_status": "ready",
                "final_decision": "HOLD",
                "reason": "No take-profit or exit condition is triggered",
            },
            {
                "symbol": "CINF",
                "profit_action": "hold",
                "risk_status": "approved",
                "preview_status": "ready",
                "final_decision": "HOLD",
                "reason": "No take-profit or exit condition is triggered",
            },
        ],
    }


def test_latest_summary_path_encodes_filters():
    assert latest_summary_path(account_id=1, bucket="value_rebound") == "/review-history/latest?account_id=1&bucket=value_rebound"


def test_render_markdown_contains_key_summary_values():
    markdown = render_markdown(sample_result())

    assert "# Latest Review History Summary — value_rebound" in markdown
    assert "Latest review run: `bucket-review-value_rebound-20260701`" in markdown
    assert "- Reviewed positions: `2`" in markdown
    assert "- Orders submitted: `false`" in markdown
    assert "| ACGL | hold | approved | ready | HOLD |" in markdown
    assert "Final decisions: `HOLD: 2`" in markdown


def test_fetch_latest_summary_wraps_database_response(monkeypatch):
    def fake_get_json(base_url, path, api_key=None, timeout=30):
        assert path == "/review-history/latest?account_id=1&bucket=value_rebound"
        return {"status": "success", "data": sample_summary()}

    monkeypatch.setattr("scripts.render_latest_review_history_summary.get_json", fake_get_json)
    result = fetch_latest_summary("http://localhost:8004", "dev_database_key", account_id="1", bucket="value_rebound")

    assert result["response"]["status"] == "success"
    assert result["summary"]["bucket"] == "value_rebound"
