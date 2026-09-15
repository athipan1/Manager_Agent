"""Read-only session provenance and fold diagnostics for the existing report."""

def category(rejection):
    code = str(rejection.get("reason_code") or "").upper()
    if any(word in code for word in ("CONTRACT", "SCHEMA", "MISMATCH", "UNKNOWN_STRATEGY")):
        return "contract_failure"
    if any(word in code for word in ("STALE", "MISSING", "UNVERIFIED", "INCOMPLETE", "INSUFFICIENT_HISTORY")):
        return "data_failure"
    if any(word in code for word in ("TIMEOUT", "UNAVAILABLE", "INTERNAL_ERROR")):
        return "operational_failure"
    if code.startswith(("BACKTEST_NESTED_OOS_", "BACKTEST_WALK_FORWARD_", "BUCKET_")) or code in {
        "BUY_VERDICT_REQUIRED", "FINAL_SCORE_BELOW_THRESHOLD", "BACKTEST_NO_ELIGIBLE_STRATEGY",
        "SCANNER_OPPORTUNITY_MARKET_CLOSED", "RISK_REJECTED", "SCANNER_OPPORTUNITY_REVIEW",
    }:
        return "policy_rejection"
    return "unclassified_requires_review"


def session_snapshots(value, parent_symbol=None):
    found = {}
    if isinstance(value, dict):
        symbol = value.get("symbol") or parent_symbol
        snapshot = value.get("market_snapshot")
        if isinstance(snapshot, dict) and (snapshot.get("symbol") or symbol):
            found[snapshot.get("symbol") or symbol] = snapshot
        context = value.get("execution_context")
        if symbol and isinstance(context, dict) and context.get("quote_status"):
            found.setdefault(symbol, {"symbol": symbol,
                "session_trace": context.get("session_trace") or {
                    "status": "historical_execution_context_only",
                    "symbol": symbol, "quote_timestamp": context.get("quote_timestamp"),
                    "quote_age_seconds": context.get("quote_age_seconds"),
                    "quote_status": context.get("quote_status"),
                    "market_session": context.get("market_session"),
                    "market_open": context.get("market_open"),
                    "provider_timestamp": None, "provider_timezone": None,
                    "provenance_gap": "provider snapshot not retained; do not infer provider timestamp"},
                "quote_quality": {"market_open": context.get("market_open")}})
        for child in value.values():
            for key, candidate in session_snapshots(child, symbol).items():
                if key not in found or "session_trace" not in candidate:
                    found[key] = candidate
    elif isinstance(value, list):
        for child in value:
            found.update(session_snapshots(child, parent_symbol))
    return found


def enrich_sessions(rows, source, preflight):
    snapshots = session_snapshots(source)
    preflight_clock = preflight.get("alpaca_paper") or {}
    for row in rows:
        snapshot = snapshots.get(row["symbol"], {})
        quality = snapshot.get("quote_quality") or {}
        row["session_trace"] = dict(snapshot.get("session_trace") or {
            "status": "historical_provenance_partial" if snapshot else "not_recorded",
            "symbol": row["symbol"], "snapshot_started_at": snapshot.get("fetched_at"),
            "provider_market_state": snapshot.get("marketState"),
            "provider_timestamp": snapshot.get("regularMarketTime"),
            "provider_timezone": snapshot.get("exchangeTimezoneName"),
            "provider_exchange": snapshot.get("exchange"),
            "requested_exchange": snapshot.get("requested_exchange"),
            "provider_metadata_reused": "reused_yfinance_info" in (snapshot.get("market_data_sources") or []),
            "quote_timestamp": snapshot.get("alpacaQuoteTimestamp"),
            **quality,
        })
        row["session_trace"]["cycle_preflight_clock"] = preflight_clock
        trace = row["session_trace"]
        trace.setdefault("provider_session", {
            "market_state": trace.get("provider_market_state"),
            "market_session": trace.get("provider_market_session"),
            "timestamp": trace.get("provider_timestamp"),
            "timezone": trace.get("provider_timezone"),
            "exchange": trace.get("provider_exchange"),
            "metadata_reused": trace.get("provider_metadata_reused"),
            "execution_authority": False,
        })
        trace.setdefault("broker_execution_session", {
            "market_session": trace.get("market_session") if trace.get("broker_clock") else None,
            "market_open": trace.get("market_open") if trace.get("broker_clock") else None,
            "authority": trace.get("broker_clock"),
            "status": "recorded" if trace.get("broker_clock") else "not_recorded",
        })
        # A preflight clock several minutes earlier is historical comparison, not
        # refreshed execution authority. Never overwrite the recorded session.
        row["session_trace"]["preflight_open_mismatch"] = (
            quality.get("market_open") != preflight_clock.get("market_open")
            if type(quality.get("market_open")) is bool
            and type(preflight_clock.get("market_open")) is bool else None
        )
        for rejection in row["rejections"]:
            rejection["category"] = category(rejection)


def fold_markdown(backtest):
    lines = ["", "### Fold evidence", "",
             ("Returns and drawdowns below are decimals; fees and slippage are bps per side. "
             "The current nested implementation validates within its training slice; it has no "
             "separate inner validation partition. The final holdout remains separately sealed.")]
    scopes = [("nested_outer_oos", backtest["nested_outer_oos"])]
    scopes += [(str(item.get("strategy_id")) + " candidate_oos", item["candidate_oos"])
               for item in backtest["all_strategy_results"]]
    for label, scope in scopes:
        lines += ["", "#### " + label, "",
                  "| Fold | Training period | Validation | OOS period | Trades | Return | Sharpe | Sortino | Max DD | Fee bps | Slippage bps | Fees paid | Decision / reason |",
                  "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for window in scope["windows"]:
            metrics = window.get("metrics") or {}
            costs = window.get("oos_execution_costs") or {}
            reasons = [str(item.get("strategy_id")) + ": " + ", ".join(item.get("failed_inner_gates") or [])
                       for item in window.get("training_candidates") or [] if item.get("failed_inner_gates")]
            if not reasons and window.get("decision") == "NO_TRADE":
                reasons = ["cash abstention; detailed training gates not recorded in historical artifact"]
            values = [window.get("window"),
                      str(window.get("train_start")) + " → " + str(window.get("train_end")),
                      (window.get("validation_period") or {}).get("status", "no separate slice recorded"),
                      str(window.get("test_start")) + " → " + str(window.get("test_end")),
                      *[metrics.get(key) for key in ("trade_count", "return_pct", "sharpe_ratio", "sortino_ratio", "max_drawdown")],
                      costs.get("fee_bps_per_side", backtest["cost_model"].get("fee_bps")),
                      costs.get("slippage_bps_per_side", backtest["cost_model"].get("slippage_bps")),
                      costs.get("fees_paid"), str(window.get("decision")) + "; " + "; ".join(reasons)]
            lines.append("| " + " | ".join("N/A" if value is None else str(value) for value in values) + " |")
        lines += ["", "Training-slice metrics (not outer OOS performance):", "",
                  "| Fold | Strategy | Trades | Return | Sharpe | Sortino | Max DD | Fees paid | Parameters | Failed inner gates |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---|---|"]
        for window in scope["windows"]:
            candidates = window.get("training_candidates") or []
            if not candidates and window.get("train_metrics"):
                candidates = [{"strategy_id": label, "metrics": window["train_metrics"],
                               "execution_costs": window.get("train_execution_costs") or {}}]
            for candidate in candidates:
                metrics = candidate.get("metrics") or {}
                values = [window.get("window"), candidate.get("strategy_id"),
                          *[metrics.get(key) for key in ("trade_count", "return_pct", "sharpe_ratio", "sortino_ratio", "max_drawdown")],
                          (candidate.get("execution_costs") or {}).get("fees_paid"),
                          candidate.get("effective_parameters", "not recorded"),
                          candidate.get("failed_inner_gates", "not recorded")]
                lines.append("| " + " | ".join("N/A" if value is None else str(value) for value in values) + " |")
    return lines
