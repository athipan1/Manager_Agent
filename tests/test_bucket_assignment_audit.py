from scripts.render_bucket_assignment_audit import build_assignment_audit, fetch_assignment_audit, render_markdown


def positions_fixture():
    return [
        {"symbol": "ACGL", "qty": 82},
        {"symbol": "ADBE", "qty": 12},
        {"symbol": "BKNG", "qty": 1},
        {"symbol": "CINF", "qty": 46},
    ]


def hints_fixture():
    return {
        "ACGL": {"bucket": "value_rebound", "source": "database_agent", "reason": "value bucket"},
        "ADBE": {"bucket": "core_dividend", "source": "database_agent", "reason": "core bucket"},
        "CINF": {"bucket": "value_rebound", "source": "database_agent", "reason": "value bucket"},
    }


def test_assignment_audit_finds_missing_bucket():
    audit = build_assignment_audit(positions_fixture(), hints_fixture())

    assert audit["positions_seen"] == 4
    assert audit["assigned_positions"] == 3
    assert audit["unassigned_positions_count"] == 1
    assert audit["bucket_distribution"] == {"core_dividend": 1, "unassigned": 1, "value_rebound": 2}
    assert audit["unassigned_positions"][0]["symbol"] == "BKNG"
    assert audit["action_required"] is True


def test_assignment_markdown_lists_missing_bucket():
    markdown = render_markdown(build_assignment_audit(positions_fixture(), hints_fixture()))

    assert "# Bucket Assignment Audit" in markdown
    assert "- Unassigned positions: `1`" in markdown
    assert "| BKNG | 1 | unassigned | missing |" in markdown


def test_fetch_assignment_audit(monkeypatch):
    def fake_get_json(base_url, path, api_key=None, timeout=30):
        if path == "/positions":
            return {"status": "success", "data": positions_fixture()}
        if path == "/accounts/1/position-buckets":
            return {
                "status": "success",
                "data": [
                    {"symbol": "ACGL", "strategy_bucket": "value_rebound", "strategy_bucket_source": "database_agent"},
                    {"symbol": "ADBE", "strategy_bucket": "core_dividend", "strategy_bucket_source": "database_agent"},
                    {"symbol": "CINF", "strategy_bucket": "value_rebound", "strategy_bucket_source": "database_agent"},
                ],
            }
        raise AssertionError(path)

    monkeypatch.setattr("scripts.render_bucket_assignment_audit.get_json", fake_get_json)
    audit = fetch_assignment_audit("http://localhost:8006", "dev_execution_key", "http://localhost:8004", "dev_database_key", "1")

    assert audit["positions_seen"] == 4
    assert audit["unassigned_positions_count"] == 1
    assert audit["unassigned_positions"][0]["symbol"] == "BKNG"
