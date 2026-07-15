from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


BALANCED_STRATEGY_IDS = (
    "sma-crossover-balanced-v1",
    "trend-following-balanced-v1",
    "mean-reversion-balanced-v1",
    "breakout-balanced-v1",
)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _symbols_from_env() -> list[str]:
    raw = os.getenv("BACKTEST_SYMBOLS") or os.getenv("BACKTEST_SYMBOL", "AAPL")
    symbols = list(
        dict.fromkeys(
            item.strip().upper()
            for item in raw.split(",")
            if item.strip()
        )
    )
    if not symbols:
        raise ValueError("BACKTEST_SYMBOLS must contain at least one symbol")
    invalid = [
        symbol
        for symbol in symbols
        if re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", symbol) is None
    ]
    if invalid:
        raise ValueError(f"BACKTEST_SYMBOLS contains invalid symbols: {invalid}")
    max_symbols = int(os.getenv("BACKTEST_MAX_SYMBOLS", "10"))
    if len(symbols) > max_symbols:
        raise ValueError(
            f"BACKTEST_SYMBOLS contains {len(symbols)} symbols; "
            f"maximum is {max_symbols}"
        )
    return symbols


def _default_date_range() -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=730)
    return start.isoformat(), end.isoformat()


def _load_backtest_runtime() -> Dict[str, Any]:
    repo_root = Path(
        os.getenv("BACKTEST_AGENT_REPO", "../Backtest_Agent")
    ).resolve()
    if not (repo_root / "app" / "multi_strategy.py").exists():
        raise RuntimeError(
            "Backtest_Agent multi-strategy runtime is unavailable at "
            f"{repo_root}"
        )
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.data_provider import AlpacaMarketDataProvider, dataset_fingerprint
    from app.multi_strategy import (
        MultiStrategyBacktestRequest,
        build_run_request,
        resolve_strategy_id,
        run_multi_strategy_backtest,
    )
    from app.publisher import ENGINE_VERSION, publish_backtest_result

    return {
        "AlpacaMarketDataProvider": AlpacaMarketDataProvider,
        "dataset_fingerprint": dataset_fingerprint,
        "MultiStrategyBacktestRequest": MultiStrategyBacktestRequest,
        "build_run_request": build_run_request,
        "resolve_strategy_id": resolve_strategy_id,
        "run_multi_strategy_backtest": run_multi_strategy_backtest,
        "ENGINE_VERSION": ENGINE_VERSION,
        "publish_backtest_result": publish_backtest_result,
    }


def _selection_criteria() -> Dict[str, Any]:
    return {
        "min_trades": int(os.getenv("BACKTEST_SELECTION_MIN_TRADES", "10")),
        "min_annualized_return": float(
            os.getenv("BACKTEST_SELECTION_MIN_ANNUALIZED_RETURN", "0.05")
        ),
        "min_sharpe_ratio": float(
            os.getenv("BACKTEST_SELECTION_MIN_SHARPE_RATIO", "0.80")
        ),
        "min_profit_factor": float(
            os.getenv("BACKTEST_SELECTION_MIN_PROFIT_FACTOR", "1.20")
        ),
        "max_drawdown_floor": float(
            os.getenv("BACKTEST_SELECTION_MAX_DRAWDOWN_FLOOR", "-0.20")
        ),
        "min_excess_return": float(
            os.getenv("BACKTEST_SELECTION_MIN_EXCESS_RETURN", "0.0")
        ),
        "max_kill_switch_events": int(
            os.getenv("BACKTEST_SELECTION_MAX_KILL_SWITCH_EVENTS", "0")
        ),
    }


def _request_kwargs(*, symbol: str, bars: Iterable[Any]) -> Dict[str, Any]:
    return {
        "symbols": [symbol],
        "initial_equity": float(
            os.getenv("BACKTEST_INITIAL_EQUITY", "100000")
        ),
        "bars": {
            symbol: [
                bar.model_dump(mode="json")
                if hasattr(bar, "model_dump")
                else bar
                for bar in bars
            ]
        },
        "risk_per_trade": float(
            os.getenv("BACKTEST_RISK_PER_TRADE", "0.01")
        ),
        "max_position_pct": float(
            os.getenv("BACKTEST_MAX_POSITION_PCT", "0.10")
        ),
        "stop_loss_pct": float(
            os.getenv("BACKTEST_STOP_LOSS_PCT", "0.03")
        ),
        "reward_risk_ratio": float(
            os.getenv("BACKTEST_REWARD_RISK_RATIO", "2.0")
        ),
        "fee_bps": float(os.getenv("BACKTEST_FEE_BPS", "10")),
        "slippage_bps": float(os.getenv("BACKTEST_SLIPPAGE_BPS", "5")),
        "use_risk_agent": _bool_env("BACKTEST_USE_RISK_AGENT", True),
        "emergency_halt": _bool_env("BACKTEST_EMERGENCY_HALT", False),
        "max_trades_per_day": int(
            os.getenv("BACKTEST_MAX_TRADES_PER_DAY", "5")
        ),
        "force_close_at_end": _bool_env(
            "BACKTEST_FORCE_CLOSE_AT_END", True
        ),
        "max_total_exposure_pct": float(
            os.getenv("BACKTEST_MAX_TOTAL_EXPOSURE_PCT", "1.0")
        ),
        "max_open_positions": int(
            os.getenv("BACKTEST_MAX_OPEN_POSITIONS", "25")
        ),
        "cash_reserve_pct": float(
            os.getenv("BACKTEST_CASH_RESERVE_PCT", "0.0")
        ),
        "max_new_positions_per_bar": int(
            os.getenv("BACKTEST_MAX_NEW_POSITIONS_PER_BAR", "25")
        ),
        "periods_per_year": int(
            os.getenv("BACKTEST_PERIODS_PER_YEAR", "252")
        ),
        "annual_risk_free_rate": float(
            os.getenv("BACKTEST_ANNUAL_RISK_FREE_RATE", "0.0")
        ),
        "max_volume_participation_pct": float(
            os.getenv("BACKTEST_MAX_VOLUME_PARTICIPATION_PCT", "1.0")
        ),
        "market_impact_bps": float(
            os.getenv("BACKTEST_MARKET_IMPACT_BPS", "0.0")
        ),
        "selection_criteria": _selection_criteria(),
    }


def _deterministic_run_id(
    *,
    symbol: str,
    strategy_id: str,
    fingerprint: str,
    parameters: Dict[str, Any],
    timeframe: str,
    engine_version: str,
) -> str:
    identity = {
        "symbol": symbol,
        "strategy_id": strategy_id,
        "dataset_fingerprint": fingerprint,
        "parameters": parameters,
        "timeframe": timeframe,
        "engine_version": engine_version,
        "selection_profile": "balanced_v1",
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"backtest-selection-{digest[:24]}"


def _find_selected_candidate(
    *,
    request: Any,
    strategy_id: str,
    resolve_strategy_id: Any,
) -> Any:
    for candidate in request.candidates:
        if resolve_strategy_id(candidate, request) == strategy_id:
            return candidate
    raise RuntimeError(
        f"selected strategy_id {strategy_id!r} has no matching candidate"
    )


def _slug_symbol(symbol: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", symbol.lower()).strip("-")


def _preserve_legacy_report(report_path: Path) -> Optional[Path]:
    if not report_path.exists():
        return None
    legacy_path = report_path.with_name("hourly-backtest-fixed-strategy-result.json")
    legacy_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return legacy_path


def run_hourly_multi_strategy(report_path: Path) -> Dict[str, Any]:
    runtime = _load_backtest_runtime()
    symbols = _symbols_from_env()
    timeframe = os.getenv("BACKTEST_TIMEFRAME", "1d")
    default_start, default_end = _default_date_range()
    start = os.getenv("BACKTEST_START") or default_start
    end = os.getenv("BACKTEST_END") or default_end
    minimum_bars = int(os.getenv("BACKTEST_MINIMUM_BARS", "252"))
    bar_limit = int(os.getenv("BACKTEST_BAR_LIMIT", "10000"))
    skill_id = os.getenv("BACKTEST_SKILL_ID", "hourly-sma-crossover")
    account_id = os.getenv("BACKTEST_ACCOUNT_ID", "1")
    publish_to_database = _bool_env("PUBLISH_TO_DATABASE", True)
    batch_seed = os.getenv("GITHUB_RUN_ID") or datetime.now(timezone.utc).isoformat()
    batch_id = f"multi-strategy-{batch_seed}"

    provider = runtime["AlpacaMarketDataProvider"](
        api_key=os.getenv("ALPACA_API_KEY_ID", ""),
        secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        base_url=os.getenv(
            "ALPACA_DATA_API_URL", "https://data.alpaca.markets"
        ),
        feed=os.getenv("ALPACA_DATA_FEED", "iex"),
    )

    items = []
    strategy_ids_by_symbol: Dict[str, str] = {}
    for symbol in symbols:
        try:
            bars = provider.fetch_bars(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                minimum_bars=minimum_bars,
                limit=bar_limit,
            )
            fingerprint = runtime["dataset_fingerprint"]({symbol: bars})
            request = runtime["MultiStrategyBacktestRequest"](
                **_request_kwargs(symbol=symbol, bars=bars)
            )
            selection = runtime["run_multi_strategy_backtest"](request)
            selection_json = selection.model_dump(mode="json")

            if selection.best_eligible is None:
                items.append(
                    {
                        "symbol": symbol,
                        "status": "no_eligible_strategy",
                        "selected_strategy_id": None,
                        "published": False,
                        "publish_status": "skipped",
                        "selection": selection_json,
                        "database_payload": None,
                        "database_response": None,
                        "error": None,
                    }
                )
                continue

            selected_strategy_id = selection.best_eligible.strategy_id
            candidate = _find_selected_candidate(
                request=request,
                strategy_id=selected_strategy_id,
                resolve_strategy_id=runtime["resolve_strategy_id"],
            )
            run_request = runtime["build_run_request"](candidate, request)
            selected_result = selection.selected_result
            if selected_result is None:
                raise RuntimeError(
                    "best_eligible was returned without selected_result"
                )
            run_id = _deterministic_run_id(
                symbol=symbol,
                strategy_id=selected_strategy_id,
                fingerprint=fingerprint,
                parameters=selection.best_eligible.effective_parameters,
                timeframe=timeframe,
                engine_version=runtime["ENGINE_VERSION"],
            )
            publish_report = {
                "status": "skipped",
                "payload": None,
                "database_response": None,
            }
            if publish_to_database:
                publish_report = runtime["publish_backtest_result"](
                    request=run_request,
                    result=selected_result,
                    account_id=account_id,
                    run_id=run_id,
                    skill_id=skill_id,
                    strategy_id=selected_strategy_id,
                    timeframe=timeframe,
                    metadata={
                        "multi_strategy_selected": True,
                        "selection_profile": "balanced_v1",
                        "selection_batch_id": batch_id,
                        "selection_rank": selection.best_eligible.rank,
                        "selection_score": selection.best_eligible.score,
                        "selection_gates": selection.best_eligible.gates,
                        "selection_criteria": selection.selection_criteria.model_dump(
                            mode="json"
                        ),
                        "candidate_source": selection.candidate_source,
                        "dataset_fingerprint": fingerprint,
                        "data_start": start,
                        "data_end": end,
                        "bar_count": len(bars),
                        "trigger": os.getenv("GITHUB_EVENT_NAME", "manual"),
                        "workflow": os.getenv(
                            "GITHUB_WORKFLOW", "hourly-auto-trading"
                        ),
                        "repository": os.getenv(
                            "GITHUB_REPOSITORY", "unknown"
                        ),
                        "workflow_run_id": os.getenv(
                            "GITHUB_RUN_ID", "unknown"
                        ),
                        "storage_only": True,
                    },
                )
            publish_status = str(publish_report.get("status") or "failed")
            published = publish_to_database and publish_status == "success"
            if publish_to_database and not published:
                raise RuntimeError(
                    "Database publish did not succeed for selected strategy: "
                    f"{publish_status}"
                )

            strategy_ids_by_symbol[symbol] = selected_strategy_id
            items.append(
                {
                    "symbol": symbol,
                    "status": "eligible_strategy_found",
                    "run_id": run_id,
                    "selected_strategy_id": selected_strategy_id,
                    "published": published,
                    "publish_status": publish_status,
                    "selection": selection_json,
                    "result": selected_result.model_dump(mode="json"),
                    "database_payload": publish_report.get("payload"),
                    "database_response": publish_report.get(
                        "database_response"
                    ),
                    "error": None,
                }
            )
        except Exception as exc:
            items.append(
                {
                    "symbol": symbol,
                    "status": "failed",
                    "selected_strategy_id": None,
                    "published": False,
                    "publish_status": "failed",
                    "selection": None,
                    "database_payload": None,
                    "database_response": None,
                    "error": str(exc),
                }
            )

    eligible_symbols = [
        item["symbol"]
        for item in items
        if item["status"] == "eligible_strategy_found"
    ]
    ineligible_symbols = [
        item["symbol"]
        for item in items
        if item["status"] == "no_eligible_strategy"
    ]
    failed_symbols = [
        item["symbol"] for item in items if item["status"] == "failed"
    ]
    published_count = sum(1 for item in items if item.get("published"))
    all_succeeded = not failed_symbols
    all_eligible_published = published_count == len(eligible_symbols)
    publish_status = (
        "success"
        if all_succeeded and all_eligible_published
        else "partial_failure"
        if eligible_symbols or ineligible_symbols
        else "failed"
    )
    output = {
        "status": "success" if all_succeeded else "error",
        "agent_type": "backtest-agent",
        "data": {
            "mode": "multi_strategy_selection",
            "selection_profile": "balanced_v1",
            "batch_id": batch_id,
            "symbols": symbols,
            "strategy_ids": list(BALANCED_STRATEGY_IDS),
            "strategy_ids_by_symbol": strategy_ids_by_symbol,
            "items": items,
            "eligible_symbols": eligible_symbols,
            "ineligible_symbols": ineligible_symbols,
            "failed_symbols": failed_symbols,
            "eligible_count": len(eligible_symbols),
            "ineligible_count": len(ineligible_symbols),
            "published_count": published_count,
            "published": all_succeeded and all_eligible_published,
            "publish_status": publish_status,
            "all_succeeded": all_succeeded,
            "selection_complete": all_succeeded,
            "no_trade_is_success": True,
        },
        "error": (
            None
            if all_succeeded
            else "One or more multi-strategy Backtests failed operationally."
        ),
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path = _preserve_legacy_report(report_path)
    if legacy_path is not None:
        output["data"]["legacy_fixed_strategy_report"] = str(legacy_path)
    report_path.write_text(
        json.dumps(output, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for item in items:
        item_path = report_path.parent / (
            f"hourly-backtest-{_slug_symbol(item['symbol'])}.json"
        )
        item_path.write_text(
            json.dumps(item, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return output


def main() -> None:
    report_path = Path(
        os.getenv(
            "BACKTEST_REPORT_PATH",
            "reports/hourly-backtest-result.json",
        )
    )
    output = run_hourly_multi_strategy(report_path)
    print(json.dumps(output, indent=2, sort_keys=True))
    if output.get("status") != "success":
        raise SystemExit(
            "One or more multi-strategy Backtests failed; see report."
        )


if __name__ == "__main__":
    main()
