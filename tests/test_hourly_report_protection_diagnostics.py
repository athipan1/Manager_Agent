from scripts.render_hourly_portfolio_report import render_protection_diagnostics


def test_render_protection_diagnostics_shows_stop_only_upgrade_action():
    lines = []
    render_protection_diagnostics(
        lines,
        {
            "status": "success",
            "data": {
                "mode": "diagnostic_only",
                "safety": "read_only_no_orders_submitted",
                "summary": {
                    "position_count": 1,
                    "open_order_count": 1,
                    "stop_only_count": 1,
                    "needs_bracket_upgrade_count": 1,
                    "unprotected_position_count": 0,
                    "orders_submitted": False,
                },
                "positions": [
                    {
                        "symbol": "ACGL",
                        "position_qty": "82",
                        "has_protective_stop": True,
                        "has_take_profit": False,
                        "has_bracket": False,
                        "open_order_count": 1,
                        "protection_status": "stop_only",
                        "recommended_action": "needs_bracket_upgrade",
                    }
                ],
            },
        },
    )

    output = "\n".join(lines)
    assert "## Broker Protection Diagnostics" in output
    assert "Needs Bracket Upgrade: `1`" in output
    assert "Orders Submitted By Diagnostic: `False`" in output
    assert "ACGL" in output
    assert "stop_only" in output
    assert "needs_bracket_upgrade" in output
    assert "diagnostic-only" in output


def test_render_protection_diagnostics_ignores_empty_payload():
    lines = []
    render_protection_diagnostics(lines, {})

    assert lines == []
