from scripts.store_bucket_review_history import build_payload, store_history


def sample_report():
    return {
        "generated_at": "2026-07-01T13:48:06.809465+00:00",
        "bucket": "value_rebound",
        "mode": "BUCKET_PROFIT_REVIEW_REPORT_ONLY",
        "summary": {
            "reviewed_positions": 2,
            "risk_approved": 2,
            "execution_preview_ready": 2,
        },
        "safety": {"orders_submitted": False},
        "reviewed_positions": [
            {
                "symbol": "ACGL",
                "bucket": "value_rebound",
                "profit_plan": {"primary_action": "hold"},
                "risk_status": "approved",
                "execution_preview_status": "ready",
            }
        ],
    }


def test_build_payload_uses_bucket_and_stable_review_run_id():
    payload = build_payload(sample_report(), account_id=1)
    assert payload["account_id"] == 1
    assert payload["bucket"] == "value_rebound"
    assert payload["source"] == "manager-agent"
    assert payload["status"] == "completed"
    assert payload["review_run_id"].startswith("bucket-review-value_rebound-")
    assert payload["report"]["summary"]["risk_approved"] == 2


def test_store_history_posts_to_database(monkeypatch):
    calls = []

    def fake_post_json(base_url, path, payload, api_key=None, timeout=30):
        calls.append({"base_url": base_url, "path": path, "payload": payload, "api_key": api_key})
        return {"status": "success", "data": {"review_run_id": payload["review_run_id"]}}

    monkeypatch.setattr("scripts.store_bucket_review_history.post_json", fake_post_json)
    result = store_history(sample_report(), "http://localhost:8004", "dev_database_key", account_id="1")

    assert calls[0]["path"] == "/review-history"
    assert calls[0]["api_key"] == "dev_database_key"
    assert calls[0]["payload"]["bucket"] == "value_rebound"
    assert result["response"]["status"] == "success"
