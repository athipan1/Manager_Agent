from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from scripts.run_multi_strategy_backtests import (
    BALANCED_STRATEGY_IDS,
    _bool_env,
    _default_date_range,
    _find_selected_candidate,
    _preserve_legacy_report,
    _request_kwargs,
    _slug_symbol,
    _symbols_from_env,
)


WALK_FORWARD_PROFILE = "rolling_walk_forward_v1"
WALK_FORWARD_ENDPOINT = "/backtest/multi-strategy/walk-forward"


def _load_walk_forward_runtime() -> Dict[str, Any]:
    repo_root = Path(os.getenv("BACKTEST_AGENT_REPO", "../Backtest_Agent")).resolve()
    required = (
        repo_root / "app" / "multi_strategy_walk_forward.py",
        repo_root / "app" / "publisher.py",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(
            "Backtest_Agent walk-forward runtime is unavailable; missing: "
            + ", ".join(missing)
        )
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.data_provider import AlpacaMarketDataProvider, dataset_fingerprint
    from app.multi_strategy import build_run_request, resolve_strategy_id
    from app.multi_strategy_walk_forward import (
        WalkForwardMultiStrategyRequest,
        WalkForwardMultiStrategyResult,
    )
    from app.publisher import ENGINE_VERSION, publish_backtest_result

    return {
        "AlpacaMarketDataProvider": AlpacaMarketDataProvider,
        "dataset_fingerprint": dataset_fingerprint,
        "WalkForwardMultiStrategyRequest": WalkForwardMultiStrategyRequest,
        "WalkForwardMultiStrategyResult": WalkForwardMultiStrategyResult,
        "build_run_request": build_run_request,
        "resolve_strategy_id": resolve_strategy_id,
        "ENGINE_VERSION": ENGINE_VERSION,
        "publish_backtest_result": publish_backtest_result,
    }


def _walk_forward_criteria() -> Dict[str, Any]:
    return {
        "train_bars": int(os.getenv("BACKTEST_WALK_FORWARD_TRAIN_BARS", "126")),
        "test_bars": int(os.getenv("BACKTEST_WALK_FORWARD_TEST_BARS", "126")),
        "step_bars": int(os.getenv("BACKTEST_WALK_FORWARD_STEP_BARS", "63")),
        "min_windows": int(os.getenv("BACKTEST_WALK_FORWARD_MIN_WINDOWS", "4")),
        "min_window_trades": int(
            os.getenv("BACKTEST_WALK_FORWARD_MIN_WINDOW_TRADES", "1")
        ),
        "min_profitable_window_rate": float(
            os.getenv("BACKTEST_WALK_FORWARD_MIN_PROFITABLE_RATE", "0.60")
        ),
        "min_median_sharpe_ratio": float(
            os.getenv("BACKTEST_WALK_FORWARD_MIN_MEDIAN_SHARPE", "0.70")
        ),
        "min_median_profit_factor": float(
            os.getenv("BACKTEST_WALK_FORWARD_MIN_MEDIAN_PROFIT_FACTOR", "1.10")
        ),
        "max_drawdown_floor": float(
            os.getenv("BACKTEST_WALK_FORWARD_MAX_DRAWDOWN_FLOOR", "-0.20")
        ),
        "max_kill_switch_events": int(
            os.getenv("BACKTEST_WALK_FORWARD_MAX_KILL_SWITCH_EVENTS", "0")
        ),
    }


def _walk_forward_request_kwargs(*, symbol: str, bars: list[Any]) -> Dict[str, Any]:
    payload = _request_kwargs(symbol=symbol, bars=bars)
    payload["walk_forward_criteria"] = _walk_forward_criteria()
    return payload


def _deterministic_walk_forward_run_id(
    *,
    symbol: str,
    strategy_id: str,
    fingerprint: str,
    parameters: Dict[str, Any],
    timeframe: str,
    engine_version: str,
    walk_forward_criteria: Dict[str, Any],
) -> str:
    identity = {
        "symbol": symbol,
        "strategy_id": strategy_id,
        "dataset_fingerprint": fingerprint,
        "parameters": parameters,
        "timeframe": timeframe,
        "engine_version": engine_version,
        "selection_profile": "balanced_v1",
        "validation_profile": WALK_FORWARD_PROFILE,
        "walk_forward_criteria": walk_forward_criteria,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"backtest-walk-forward-{digest[:24]}"


def _post_json(
    *, base_url: str, path: str, payload: Dict[str, Any], timeout: float
) -> Dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Backtest_Agent walk-forward endpoint returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Backtest_Agent walk-forward endpoint is unreachable: {exc.reason}"
        ) from exc
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise RuntimeError("Backtest_Agent returned a non-object response")
    return parsed


def _run_walk_forward_selection(*, request: Any, runtime: Dict[str, Any]) -> Any:
    response = _post_json(
        base_url=os.getenv("BACKTEST_AGENT_URL", "http://localhost:8016"),
        path=os.getenv("BACKTEST_WALK_FORWARD_ENDPOINT", WALK_FORWARD_ENDPOINT),
        payload=request.model_dump(mode="json"),
        timeout=float(os.getenv("BACKTEST_WALK_FORWARD_TIMEOUT_SECONDS", "900")),
    )
    if response.get("status") != "success" or not isinstance(response.get("data"), dict):
        raise RuntimeError(
            "Backtest_Agent walk-forward selection failed: "
            + json.dumps(response.get("error") or response, sort_keys=True)
        )
    return runtime["WalkForwardMultiStrategyResult"].model_validate(response["data"])


def _walk_forward_metadata(selection: Any) -> Dict[str, Any]:
    if selection.best_eligible is None:
        raise RuntimeError("walk-forward metadata requested without best_eligible")
    evidence = selection.best_eligible.walk_forward.model_dump(mode="json")
    return {
        "validation_profile": WALK_FORWARD_PROFILE,
        "walk_forward_required": True,
        "walk_forward_passed": bool(evidence.get("passed")),
        "walk_forward_status": evidence.get("status"),
        "walk_forward_stability_score": evidence.get("stability_score"),
        "walk_forward_evaluated_windows": evidence.get("evaluated_windows"),
        "walk_forward_profitable_window_rate": evidence.get("profitable_window_rate"),
        "walk_forward_median_sharpe_ratio": evidence.get("median_sharpe_ratio"),
        "walk_forward_median_profit_factor": evidence.get("median_profit_factor"),
        "walk_forward_worst_max_drawdown": evidence.get("worst_max_drawdown"),
        "walk_forward_validation": evidence,
        "walk_forward_criteria": selection.walk_forward_criteria.model_dump(mode="json"),
    }


def run_hourly_walk_forward_multi_strategy(report_path: Path) -> Dict[str, Any]:
    runtime = _load_walk_forward_runtime()
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
    batch_id = f"walk-forward-multi-strategy-{batch_seed}"

    provider = runtime["AlpacaMarketDataProvider"](
        api_key=os.getenv("ALPACA_API_KEY_ID", ""),
        secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        base_url=os.getenv("ALPACA_DATA_API_URL", "https://data.alpaca.markets"),
        feed=os.getenv("ALPACA_DATA_FEED", "iex"),
    )

    items: list[Dict[str, Any]] = []
    strategy_ids_by_symbol: Dict[str, str] = {}
    stability_by_symbol: Dict[str, Dict[str, Any]] = {}
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
            request = runtime["WalkForwardMultiStrategyRequest"](
                **_walk_forward_request_kwargs(symbol=symbol, bars=bars)
            )
            selection = _run_walk_forward_selection(request=request, runtime=runtime)
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
                raise RuntimeError("best_eligible was returned without selected_result")
            if not selection.best_eligible.walk_forward.passed:
                raise RuntimeError(
                    "best_eligible was returned without passing walk-forward evidence"
                )
            walk_forward_metadata = _walk_forward_metadata(selection)
            run_id = _deterministic_walk_forward_run_id(
                symbol=symbol,
                strategy_id=selected_strategy_id,
                fingerprint=fingerprint,
                parameters=selection.best_eligible.effective_parameters,
                timeframe=timeframe,
                engine_version=runtime["ENGINE_VERSION"],
                walk_forward_criteria=walk_forward_metadata["walk_forward_criteria"],
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
                        "multi_strategy_walk_forward_selected": True,
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
                        **walk_forward_metadata,
                        "trigger": os.getenv("GITHUB_EVENT_NAME", "manual"),
                        "workflow": os.getenv("GITHUB_WORKFLOW", "hourly-auto-trading"),
                        "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
                        "workflow_run_id": os.getenv("GITHUB_RUN_ID", "unknown"),
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
            stability_by_symbol[symbol] = walk_forward_metadata
            items.append(
                {
                    "symbol": symbol,
                    "status": "eligible_strategy_found",
                    "run_id": run_id,
                    "selected_strategy_id": selected_strategy_id,
                    "published": published,
                    "publish_status": publish_status,
                    "selection": selection_json,
                    "walk_forward": walk_forward_metadata,
                    "result": selected_result.model_dump(mode="json"),
                    "database_payload": publish_report.get("payload"),
                    "database_response": publish_report.get("database_response"),
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
        item["symbol"] for item in items if item["status"] == "eligible_strategy_found"
    ]
    ineligible_symbols = [
        item["symbol"] for item in items if item["status"] == "no_eligible_strategy"
    ]
    failed_symbols = [item["symbol"] for item in items if item["status"] == "failed"]
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
            "mode": "walk_forward_multi_strategy_selection",
            "selection_profile": "balanced_v1",
            "validation_profile": WALK_FORWARD_PROFILE,
            "endpoint": WALK_FORWARD_ENDPOINT,
            "batch_id": batch_id,
            "symbols": symbols,
            "strategy_ids": list(BALANCED_STRATEGY_IDS),
            "strategy_ids_by_symbol": strategy_ids_by_symbol,
            "stability_by_symbol": stability_by_symbol,
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
            "walk_forward_required": True,
            "no_trade_is_success": True,
        },
        "error": (
            None
            if all_succeeded
            else "One or more walk-forward multi-strategy Backtests failed operationally."
        ),
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path = _preserve_legacy_report(report_path)
    if legacy_path is not None:
        output["data"]["legacy_fixed_strategy_report"] = str(legacy_path)
    report_path.write_text(
        json.dumps(output, indent=2, sort_keys=True), encoding="utf-8"
    )
    for item in items:
        item_path = report_path.parent / (
            f"hourly-backtest-{_slug_symbol(item['symbol'])}.json"
        )
        item_path.write_text(
            json.dumps(item, indent=2, sort_keys=True), encoding="utf-8"
        )
    return output


def main() -> None:
    report_path = Path(
        os.getenv("BACKTEST_REPORT_PATH", "reports/hourly-backtest-result.json")
    )
    output = run_hourly_walk_forward_multi_strategy(report_path)
    print(json.dumps(output, indent=2, sort_keys=True))
    if output.get("status") != "success":
        raise SystemExit(
            "One or more walk-forward multi-strategy Backtests failed; see report."
        )


if __name__ == "__main__":
    main()
