#!/usr/bin/env python3
"""Add browser-safe operational telemetry projections to dashboard-snapshot.v2."""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

MAX_BACKTEST_HISTORY = 50
MAX_BACKTEST_CURVE_POINTS = 2_000
MAX_BACKTEST_TRADES = 1_000
AGENT_ORDER = (
    "manager",
    "database",
    "scanner",
    "technical",
    "fundamental",
    "market_regime",
    "learning",
    "performance",
    "portfolio",
    "profit",
    "risk",
    "execution",
    "curator",
)
AGENT_NAMES = {
    "manager": "Manager",
    "database": "Database",
    "scanner": "Scanner",
    "technical": "Technical",
    "fundamental": "Fundamental",
    "market_regime": "Market Regime",
    "learning": "Learning",
    "performance": "Performance",
    "portfolio": "Portfolio",
    "profit": "Profit",
    "risk": "Risk",
    "execution": "Execution",
    "curator": "Curator",
}
SECRET_PATTERN = re.compile(
    r"(?i)(authorization|bearer\s+[a-z0-9._-]+|github[_-]?token|operator[_-]?token|"
    r"api[_-]?key|secret[_-]?key|password|database[_-]?(url|credentials?)|"
    r"ghp_[a-z0-9]+|github_pat_[a-z0-9_]+)"
)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_text(value: Any, *, limit: int = 160) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())[:limit]
    if SECRET_PATTERN.search(text):
        return "redacted"
    return text or None


def _iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _dict(value)


def _response_data(value: Mapping[str, Any]) -> dict[str, Any]:
    response = _dict(value.get("response"))
    data = _dict(response.get("data"))
    nested = _dict(data.get("data"))
    return nested or data


def _phase(snapshot: Mapping[str, Any], name: str) -> dict[str, Any]:
    for item in _list(snapshot.get("phases")):
        row = _dict(item)
        if str(row.get("name") or "").lower() == name:
            return row
    return {}


def _health(status: Any) -> str:
    normalized = str(status or "unknown").strip().lower()
    if normalized in {
        "success",
        "completed",
        "ready",
        "connected",
        "healthy",
        "ok",
        "passed",
        "active",
    }:
        return "healthy"
    if normalized in {"warning", "partial", "degraded", "partial_failure"}:
        return "degraded"
    if normalized in {
        "failure",
        "failed",
        "error",
        "cancelled",
        "critical",
        "unhealthy",
        "offline",
    }:
        return "unhealthy"
    return "unknown"


def _agent(
    agent_id: str,
    *,
    status: Any,
    health: Any | None = None,
    version: Any = None,
    last_run_at: Any = None,
) -> dict[str, Any]:
    return {
        "id": agent_id,
        "name": AGENT_NAMES[agent_id],
        "health": _health(health if health is not None else status),
        "status": _safe_text(status, limit=64) or "unknown",
        "latencyMs": None,
        "version": _safe_text(version, limit=64),
        "cpuPercent": None,
        "memoryPercent": None,
        "memoryMb": None,
        "lastRunAt": _iso(last_run_at),
    }


def _evidence_agent_status(
    discovery: Mapping[str, Any], source_name: str
) -> str | None:
    data = _response_data(discovery)
    statuses: list[str] = []
    for candidate in _list(data.get("ranked_candidates")):
        evidence = _dict(_dict(candidate).get("evidence_summary"))
        source = _dict(_dict(evidence.get("sources")).get(source_name))
        if not source or source.get("present") is False:
            continue
        statuses.append(str(source.get("status") or "unknown").lower())
    if not statuses:
        return None
    if any(
        status in {"failure", "failed", "error", "invalid"} for status in statuses
    ):
        return "failure"
    if any(status in {"partial", "warning", "degraded"} for status in statuses):
        return "partial"
    if any(status in {"complete", "success", "valid", "ready"} for status in statuses):
        return "success"
    return statuses[0]


def build_agents(
    snapshot: Mapping[str, Any], artifact_dir: Path
) -> list[dict[str, Any]]:
    generated_at = snapshot.get("generatedAt")
    workflow = _dict(snapshot.get("workflow"))
    cycle = _dict(snapshot.get("cycle"))
    preflight = _load(artifact_dir / "hourly-preflight.json")
    review = _load(artifact_dir / "hourly-position-review.json")
    discovery = _load(artifact_dir / "hourly-pre-backtest-discovery.json")
    records: dict[str, dict[str, Any]] = {}

    manager_status = _first(
        cycle.get("status"), workflow.get("conclusion"), default="unknown"
    )
    manager_health = _first(
        workflow.get("conclusion"), cycle.get("status"), default="unknown"
    )
    records["manager"] = _agent(
        "manager",
        status=manager_status,
        health=manager_health,
        last_run_at=generated_at,
    )

    database = _dict(preflight.get("railway_database"))
    if database:
        database_status = _first(
            database.get("health"),
            "ready" if database.get("ready") is True else None,
            default="unknown",
        )
        records["database"] = _agent(
            "database",
            status=database_status,
            health=database_status,
            version=database.get("version"),
            last_run_at=generated_at,
        )

    scanner_phase = _phase(snapshot, "scanner")
    if scanner_phase or discovery:
        scanner_status = _first(
            discovery.get("status"), scanner_phase.get("status"), default="unknown"
        )
        records["scanner"] = _agent(
            "scanner",
            status=scanner_status,
            last_run_at=_first(discovery.get("generated_at"), generated_at),
        )

    for agent_id in ("technical", "fundamental"):
        status = _evidence_agent_status(discovery, agent_id)
        if status:
            records[agent_id] = _agent(
                agent_id,
                status=status,
                last_run_at=_first(discovery.get("generated_at"), generated_at),
            )

    regime = _dict(review.get("market_regime"))
    if regime:
        records["market_regime"] = _agent(
            "market_regime",
            status=(
                f"regime:{_safe_text(regime.get('regime'), limit=24) or 'unknown'}"
            ),
            health="success" if regime.get("regime") else "unknown",
            last_run_at=_first(review.get("generated_at"), generated_at),
        )

    performance = _dict(review.get("performance_session_risk"))
    if performance:
        halted = performance.get("emergency_halt") is True
        records["performance"] = _agent(
            "performance",
            status="emergency_halt" if halted else "session_risk_ready",
            health="failure" if halted else "success",
            last_run_at=_first(
                performance.get("generated_at"),
                review.get("generated_at"),
                generated_at,
            ),
        )

    if review:
        review_status = _first(
            review.get("stage"),
            "success"
            if review.get("safe_for_candidate_analysis") is not False
            else "warning",
        )
        review_health = (
            "warning"
            if review.get("safe_for_candidate_analysis") is False
            else "success"
        )
        records["portfolio"] = _agent(
            "portfolio",
            status=review_status,
            health=review_health,
            last_run_at=_first(review.get("generated_at"), generated_at),
        )
        if _list(review.get("position_decisions")):
            records["profit"] = _agent(
                "profit",
                status="reviewed",
                health="success",
                last_run_at=_first(review.get("generated_at"), generated_at),
            )

    risk_phase = _phase(snapshot, "risk")
    if risk_phase or performance:
        halted = performance.get("emergency_halt") is True
        risk_status = (
            "emergency_halt"
            if halted
            else _first(risk_phase.get("status"), "session_risk_ready")
        )
        records["risk"] = _agent(
            "risk",
            status=risk_status,
            health="failure" if halted else risk_status,
            last_run_at=_first(performance.get("generated_at"), generated_at),
        )

    execution_phase = _phase(snapshot, "execution")
    if execution_phase:
        records["execution"] = _agent(
            "execution",
            status=execution_phase.get("status"),
            last_run_at=generated_at,
        )

    if _list(snapshot.get("signals")):
        records["curator"] = _agent(
            "curator",
            status="signals_published",
            health="success",
            last_run_at=generated_at,
        )

    return [records[agent_id] for agent_id in AGENT_ORDER if agent_id in records]


def _percent(value: Any, *, fraction_hint: bool = False) -> float | None:
    number = _number(value)
    if number is None:
        return None
    if fraction_hint or (0 <= abs(number) <= 1 and number != 0):
        number *= 100
    return round(number, 4)


def _bounded(value: Any, minimum: float, maximum: float) -> float | None:
    number = _number(value)
    if number is None or number < minimum or number > maximum:
        return None
    return round(number, 6)


def _sector_allocation(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _list(
        _first(source.get("sectorAllocation"), source.get("sector_allocation"), default=[])
    )
    result: list[dict[str, Any]] = []
    for row in rows[:50]:
        item = _dict(row)
        sector = _safe_text(_first(item.get("sector"), item.get("name")), limit=64)
        if not sector:
            continue
        result.append(
            {
                "sector": sector,
                "percent": _bounded(
                    _percent(_first(item.get("percent"), item.get("percentage"))),
                    0,
                    100,
                ),
                "marketValue": _bounded(
                    _first(item.get("marketValue"), item.get("market_value")),
                    0,
                    1_000_000_000_000,
                ),
            }
        )
    return result


def build_risk(
    snapshot: Mapping[str, Any], artifact_dir: Path
) -> dict[str, Any] | None:
    review = _load(artifact_dir / "hourly-position-review.json")
    report = _load(artifact_dir / "hourly-auto-trading-report.json")
    explicit = _dict(_first(review.get("risk"), report.get("risk"), default={}))
    regime = _dict(review.get("market_regime"))
    performance = _dict(review.get("performance_session_risk"))
    allocation = _dict(review.get("portfolio_allocation"))
    if not any((explicit, regime, performance, allocation)):
        return None

    gross = _first(
        explicit.get("grossExposurePercent"), explicit.get("gross_exposure_percent")
    )
    if gross in (None, ""):
        gross = _percent(allocation.get("invested_weight"), fraction_hint=True)
    else:
        gross = _percent(gross)

    net = _first(
        explicit.get("netExposurePercent"), explicit.get("net_exposure_percent")
    )
    net = _percent(net) if net not in (None, "") else None
    drawdown = _first(
        explicit.get("drawdownPercent"),
        explicit.get("drawdown_percent"),
        performance.get("drawdown_percent"),
        performance.get("drawdown_pct"),
    )
    drawdown = _percent(drawdown) if drawdown not in (None, "") else None
    limits_source = _dict(explicit.get("limits"))
    gross_limit = _first(
        limits_source.get("grossExposurePercent"),
        limits_source.get("gross_exposure_percent"),
        allocation.get("max_total_exposure_pct"),
    )
    drawdown_limit = _first(
        limits_source.get("drawdownPercent"),
        limits_source.get("drawdown_percent"),
        performance.get("max_drawdown_percent"),
    )

    emergency = None
    if (
        "emergency_halt" in performance
        or "emergencyHalt" in explicit
        or "emergency_halt" in explicit
    ):
        explicit_halt = _dict(
            _first(
                explicit.get("emergencyHalt"),
                explicit.get("emergency_halt"),
                default={},
            )
        )
        active = performance.get("emergency_halt")
        if not isinstance(active, bool):
            active = (
                explicit_halt.get("active")
                if isinstance(explicit_halt.get("active"), bool)
                else False
            )
        emergency = {
            "active": active,
            "reason": _safe_text(
                _first(
                    explicit_halt.get("reason"),
                    performance.get("emergency_halt_reason"),
                ),
                limit=200,
            ),
            "updatedAt": _iso(
                _first(
                    explicit_halt.get("updatedAt"),
                    explicit_halt.get("updated_at"),
                    performance.get("generated_at"),
                )
            ),
        }

    return {
        "riskLevel": _safe_text(
            _first(
                explicit.get("riskLevel"),
                explicit.get("risk_level"),
                regime.get("risk_level"),
            ),
            limit=32,
        ),
        "riskScore": _bounded(
            _first(explicit.get("riskScore"), explicit.get("risk_score")), 0, 100
        ),
        "grossExposurePercent": _bounded(gross, 0, 1_000),
        "netExposurePercent": _bounded(net, -1_000, 1_000),
        "drawdownPercent": _bounded(
            abs(drawdown) if drawdown is not None else None, 0, 100
        ),
        "sectorAllocation": _sector_allocation(explicit),
        "limits": {
            "grossExposurePercent": _bounded(
                _percent(gross_limit) if gross_limit not in (None, "") else None,
                0,
                1_000,
            ),
            "drawdownPercent": _bounded(
                abs(_percent(drawdown_limit))
                if drawdown_limit not in (None, "")
                else None,
                0,
                100,
            ),
        },
        "emergencyHalt": emergency,
    }


def _metric(source: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if source.get(name) not in (None, ""):
            return source.get(name)
    return None


def _percentage_metric(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    number = abs(number)
    if 0 < number <= 1:
        number *= 100
    return _bounded(number, 0, 100)


def _statistics(result: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _dict(
        _first(
            result.get("metrics"),
            result.get("statistics"),
            result.get("summary"),
            default={},
        )
    )
    merged = {**result, **metrics}
    return {
        "sharpeRatio": _bounded(
            _metric(merged, "sharpeRatio", "sharpe_ratio", "sharpe"), -100, 100
        ),
        "winRatePercent": _percentage_metric(
            _metric(
                merged,
                "winRatePercent",
                "win_rate_percent",
                "winRate",
                "win_rate",
            )
        ),
        "maxDrawdownPercent": _percentage_metric(
            _metric(
                merged,
                "maxDrawdownPercent",
                "max_drawdown_percent",
                "maxDrawdown",
                "max_drawdown",
            )
        ),
        "netProfit": _bounded(
            _metric(merged, "netProfit", "net_profit", "profit_loss", "pnl"),
            -1_000_000_000_000,
            1_000_000_000_000,
        ),
        "totalTrades": _bounded(
            _metric(merged, "totalTrades", "total_trades", "trade_count"),
            0,
            1_000_000,
        ),
    }


def _curve(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _list(
        _first(result.get("equityCurve"), result.get("equity_curve"), default=[])
    )
    output: list[dict[str, Any]] = []
    for row in rows[:MAX_BACKTEST_CURVE_POINTS]:
        item = _dict(row)
        timestamp = _iso(_first(item.get("timestamp"), item.get("at"), item.get("date")))
        equity = _bounded(
            _first(item.get("equity"), item.get("value")), 0, 1_000_000_000_000
        )
        if not timestamp or equity is None:
            continue
        output.append(
            {
                "timestamp": timestamp,
                "equity": equity,
                "drawdownPercent": _percentage_metric(
                    _first(item.get("drawdownPercent"), item.get("drawdown_percent"))
                ),
            }
        )
    return output


def _trades(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, row in enumerate(_list(result.get("trades"))[:MAX_BACKTEST_TRADES]):
        item = _dict(row)
        symbol = _safe_text(item.get("symbol"), limit=16) or "UNKNOWN"
        output.append(
            {
                "id": _safe_text(
                    _first(item.get("id"), item.get("trade_id"), f"trade-{index + 1}"),
                    limit=96,
                ),
                "symbol": symbol,
                "side": _safe_text(_first(item.get("side"), "unknown"), limit=16)
                or "unknown",
                "quantity": _bounded(
                    _first(item.get("quantity"), item.get("qty")), 0, 1_000_000_000
                ),
                "entryAt": _iso(_first(item.get("entryAt"), item.get("entry_at"))),
                "exitAt": _iso(_first(item.get("exitAt"), item.get("exit_at"))),
                "entryPrice": _bounded(
                    _first(item.get("entryPrice"), item.get("entry_price")),
                    0,
                    1_000_000_000,
                ),
                "exitPrice": _bounded(
                    _first(item.get("exitPrice"), item.get("exit_price")),
                    0,
                    1_000_000_000,
                ),
                "pnl": _bounded(
                    _first(item.get("pnl"), item.get("profit_loss")),
                    -1_000_000_000_000,
                    1_000_000_000_000,
                ),
                "status": _safe_text(
                    _first(item.get("status"), "closed"), limit=32
                )
                or "closed",
            }
        )
    return output


def _backtest_run(
    item: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    runtime_contract: Mapping[str, Any],
) -> dict[str, Any]:
    result = _dict(item.get("result"))
    selection = _dict(item.get("selection"))
    best = _dict(selection.get("best_eligible"))
    symbol = _safe_text(item.get("symbol"), limit=16) or "UNKNOWN"
    status = str(item.get("status") or "unknown")
    normalized_status = "success" if status == "eligible_strategy_found" else status
    strategy = (
        _safe_text(
            _first(
                item.get("selected_strategy_id"), best.get("strategy_id"), "unknown"
            ),
            limit=64,
        )
        or "unknown"
    )
    requested_at = _iso(
        _first(
            runtime_contract.get("timestamp"),
            result.get("requested_at"),
            result.get("requestedAt"),
        )
    )
    completed_at = _iso(
        _first(
            result.get("completed_at"),
            result.get("completedAt"),
            snapshot.get("generatedAt"),
        )
    )
    initial_capital = _bounded(
        _first(
            result.get("initialCapital"),
            result.get("initial_capital"),
            result.get("initial_equity"),
        ),
        0,
        1_000_000_000_000,
    )
    final_equity = _bounded(
        _first(
            result.get("finalEquity"),
            result.get("final_equity"),
            result.get("ending_equity"),
        ),
        0,
        1_000_000_000_000,
    )
    return {
        "id": _safe_text(
            _first(item.get("run_id"), result.get("run_id")), limit=96
        ),
        "status": _safe_text(normalized_status, limit=32) or "unknown",
        "strategy": strategy,
        "symbols": [symbol],
        "requestedAt": requested_at,
        "startedAt": _iso(
            _first(result.get("started_at"), result.get("startedAt"), requested_at)
        ),
        "completedAt": completed_at,
        "initialCapital": initial_capital,
        "finalEquity": final_equity,
        "statistics": _statistics(result),
        "equityCurve": _curve(result),
        "trades": _trades(result),
    }


def _history_run(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: run.get(key)
        for key in (
            "id",
            "status",
            "strategy",
            "symbols",
            "requestedAt",
            "startedAt",
            "completedAt",
            "initialCapital",
            "finalEquity",
            "statistics",
        )
    }


def build_backtest(
    snapshot: Mapping[str, Any], artifact_dir: Path, previous: Mapping[str, Any]
) -> dict[str, Any]:
    report = _load(artifact_dir / "hourly-backtest-result.json")
    runtime_contract = _load(artifact_dir / "backtest-runtime-contract.json")
    data = _dict(report.get("data"))
    current_runs = [
        _backtest_run(_dict(item), snapshot, runtime_contract)
        for item in _list(data.get("items"))
        if isinstance(item, Mapping)
    ]
    current_runs = [
        run for run in current_runs if run.get("id") or run.get("symbols")
    ]

    previous_backtest = _dict(previous.get("backtest"))
    previous_latest = _dict(previous_backtest.get("latestRun"))
    previous_history = [_dict(row) for row in _list(previous_backtest.get("history"))]
    latest = current_runs[0] if current_runs else previous_latest or None

    history: list[dict[str, Any]] = []
    seen: set[str] = set()
    for run in [
        *current_runs,
        *previous_history,
        *([previous_latest] if previous_latest else []),
    ]:
        key = str(
            run.get("id")
            or json.dumps(
                [run.get("strategy"), run.get("symbols"), run.get("completedAt")],
                sort_keys=True,
            )
        )
        if key in seen:
            continue
        seen.add(key)
        history.append(_history_run(run))
        if len(history) >= MAX_BACKTEST_HISTORY:
            break
    return {"latestRun": latest, "history": history}


def enrich_snapshot(
    snapshot: Mapping[str, Any],
    artifact_dir: Path,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _dict(snapshot)
    if payload.get("schemaVersion") != "dashboard-snapshot.v2":
        raise ValueError("Phase 12 telemetry enrichment requires dashboard-snapshot.v2")
    payload["agents"] = build_agents(payload, artifact_dir)
    payload["risk"] = build_risk(payload, artifact_dir)
    payload["backtest"] = build_backtest(payload, artifact_dir, _dict(previous))
    json.dumps(payload, allow_nan=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich a public dashboard snapshot with safe telemetry projections."
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    snapshot = _load(args.snapshot)
    previous = _load(args.previous) if args.previous else {}
    enriched = enrich_snapshot(snapshot, args.artifact_dir, previous)
    output = args.output or args.snapshot
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        "Enriched dashboard snapshot: "
        f"agents={len(enriched['agents'])} "
        f"risk={'published' if enriched['risk'] else 'unavailable'} "
        f"backtest_history={len(enriched['backtest']['history'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
