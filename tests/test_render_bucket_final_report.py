from scripts.render_bucket_final_report import final_decision, render_final_report


def sample_report():
    return {
        "generated_at": "2026-07-01T05:56:24Z",
        "bucket": "value_rebound",
        "mode": "BUCKET_PROFIT_REVIEW_REPORT_ONLY",
        "config": {"review_title": "Daily Value Rebound Review", "frequency": "daily"},
        "bucket_distribution": {"core_dividend": 1, "value_rebound": 2, "unassigned": 1},
        "summary": {
            "positions_seen": 4,
            "reviewed_positions": 2,
            "database_bucket_hints_applied": 3,
            "bucket_hints_applied": 0,
            "profit_agent_used": 2,
            "risk_submissions": 2,
            "risk_approved": 2,
            "risk_rejected": 0,
            "execution_preview_submissions": 2,
            "execution_preview_ready": 2,
            "execution_preview_blocked": 0,
        },
        "safety": {"advisory_only": True, "orders_submitted": False},
        "reviewed_positions": [
            {
                "symbol": "ACGL",
                "bucket": "value_rebound",
                "profit_plan": {
                    "primary_action": "hold",
                    "actions": [{"reason": "No take-profit or exit condition is triggered"}],
                },
                "risk_status": "approved",
                "execution_preview_status": "ready",
            },
            {
                "symbol": "CINF",
                "bucket": "value_rebound",
                "profit_plan": {
                    "primary_action": "hold",
                    "actions": [{"reason": "No take-profit or exit condition is triggered"}],
                },
                "risk_status": "approved",
                "execution_preview_status": "ready",
            },
        ],
    }


def test_final_decision_hold_when_risk_and_preview_ready():
    row = sample_report()["reviewed_positions"][0]
    assert final_decision(row) == "HOLD"


def test_final_decision_blocks_when_risk_rejected():
    row = sample_report()["reviewed_positions"][0].copy()
    row["risk_status"] = "rejected"
    assert final_decision(row) == "BLOCKED_BY_RISK"


def test_render_final_report_includes_summary_and_rows():
    output = render_final_report(sample_report())
    assert "Final Bucket Review Report" in output
    assert "Risk approved: `2`" in output
    assert "Preview ready: `2`" in output
    assert "| ACGL | value_rebound | hold | approved | ready | HOLD |" in output
    assert "Any submitted broker action: `false`" in output
