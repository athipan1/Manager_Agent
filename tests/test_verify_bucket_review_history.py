from scripts.verify_bucket_review_history import expected_review_run_id, verify_history


def sample_store_result():
    return {
        "request": {
            "review_run_id": "bucket-review-value_rebound-20260701",
            "report": {
                "summary": {"reviewed_positions": 2},
                "reviewed_positions": [{"symbol": "ACGL"}, {"symbol": "CINF"}],
            },
        },
        "response": {"status": "success"},
    }


def test_expected_review_run_id_reads_store_request():
    assert expected_review_run_id(sample_store_result()) == "bucket-review-value_rebound-20260701"


def test_verify_history_success(monkeypatch):
    def fake_get_json(base_url, path, api_key=None, timeout=30):
        assert path == "/review-history/bucket-review-value_rebound-20260701"
        return {
            "status": "success",
            "data": {
                "review_run_id": "bucket-review-value_rebound-20260701",
                "decisions": [{"symbol": "ACGL"}, {"symbol": "CINF"}],
            },
        }

    monkeypatch.setattr("scripts.verify_bucket_review_history.get_json", fake_get_json)
    result = verify_history(sample_store_result(), "http://localhost:8004", "dev_database_key")

    assert result["verified"] is True
    assert result["expected_decisions"] == 2
    assert result["stored_decisions"] == 2


def test_verify_history_fails_when_decision_count_mismatch(monkeypatch):
    def fake_get_json(base_url, path, api_key=None, timeout=30):
        return {
            "status": "success",
            "data": {
                "review_run_id": "bucket-review-value_rebound-20260701",
                "decisions": [{"symbol": "ACGL"}],
            },
        }

    monkeypatch.setattr("scripts.verify_bucket_review_history.get_json", fake_get_json)
    result = verify_history(sample_store_result(), "http://localhost:8004", "dev_database_key")

    assert result["verified"] is False
    assert result["expected_decisions"] == 2
    assert result["stored_decisions"] == 1
