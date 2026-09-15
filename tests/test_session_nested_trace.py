from scripts.session_nested_trace import category, enrich_sessions, fold_markdown


def test_historical_preflight_never_replaces_scanner_session():
    rows = [{"symbol": "TEST", "rejections": []}]
    source = {"market_snapshot": {"symbol": "TEST", "marketState": "PRE",
        "quote_quality": {"market_session": "premarket", "market_open": False},
        "market_data_sources": ["reused_yfinance_info"]}}
    enrich_sessions(rows, source, {"alpaca_paper": {"market_open": True}})
    trace = rows[0]["session_trace"]
    assert trace["market_open"] is False
    assert trace["preflight_open_mismatch"] is True
    assert trace["provider_metadata_reused"] is True


def test_policy_rejection_is_distinct_from_missing_data_and_bad_contract():
    assert category({"reason_code": "BACKTEST_NESTED_OOS_MEDIAN_SHARPE_RATIO"}) == "policy_rejection"
    assert category({"reason_code": "SCANNER_BROKER_SESSION_UNVERIFIED"}) == "data_failure"
    assert category({"reason_code": "BACKTEST_CYCLE_ID_MISMATCH"}) == "contract_failure"
    assert category({"reason_code": "NEW_UNKNOWN_CODE"}) == "unclassified_requires_review"


def test_abstention_is_not_reported_as_measured_strategy_oos():
    lines = fold_markdown({"nested_outer_oos": {"windows": [{
        "window": 1, "decision": "NO_TRADE", "metrics": {"trade_count": 0},
    }]}, "all_strategy_results": [], "cost_model": {"fee_bps": 10, "slippage_bps": 5}})
    text = "\n".join(lines)
    assert "cash abstention" in text and "N/A" in text
    assert "no separate inner validation partition" in text
