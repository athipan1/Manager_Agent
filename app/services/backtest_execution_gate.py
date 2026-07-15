"""Fail-closed Backtest gate for Manager execution candidates."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def _symbol(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("ticker") or value.get("symbol") or "").upper()
    return str(
        getattr(value, "ticker", None)
        or getattr(value, "symbol", None)
        or ""
    ).upper()


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _detail_timestamp(detail: Dict[str, Any]) -> datetime:
    run = detail.get("run") if isinstance(detail.get("run"), dict) else {}
    skill_result = (
        detail.get("skill_result")
        if isinstance(detail.get("skill_result"), dict)
        else {}
    )
    parsed = _parse_timestamp(
        run.get("updated_at")
        or run.get("created_at")
        or skill_result.get("updated_at")
    )
    return parsed or datetime.min.replace(tzinfo=timezone.utc)


def _deduplicated_strategy_ids(values: Iterable[str]) -> List[str]:
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in values
            if str(value).strip()
        )
    )


def _configured_strategy_ids(
    *,
    primary_strategy_id: str,
    strategy_ids: Optional[Iterable[str]],
) -> List[str]:
    """Resolve the exact strategy identities accepted by the execution gate.

    Passing an explicit empty iterable preserves the legacy single-strategy
    behavior. When omitted, production configuration may enable the deterministic
    multi-strategy suite published by Backtest_Agent.
    """

    if strategy_ids is not None:
        resolved = _deduplicated_strategy_ids(strategy_ids)
        return resolved or _deduplicated_strategy_ids([primary_strategy_id])

    try:
        from .. import config

        if config.BACKTEST_MULTI_STRATEGY_GATE_ENABLED:
            resolved = _deduplicated_strategy_ids(
                config.BACKTEST_GATE_STRATEGY_IDS
            )
            if resolved:
                return resolved
    except (AttributeError, ImportError):
        pass

    return _deduplicated_strategy_ids([primary_strategy_id])


def _decision(
    *,
    symbol: str,
    required: bool,
    detail: Dict[str, Any],
    skill_id: str,
    strategy_id: str,
    timeframe: str,
    max_age_hours: float,
    now: datetime,
    lookup_error: Optional[str],
) -> Dict[str, Any]:
    run = detail.get("run") if isinstance(detail.get("run"), dict) else {}
    skill_result = (
        detail.get("skill_result")
        if isinstance(detail.get("skill_result"), dict)
        else {}
    )
    latest_run_id = run.get("run_id")
    reasons: List[str] = []

    if not required:
        return {
            "symbol": symbol,
            "allowed": True,
            "rejection_codes": [],
            "latest_run_id": latest_run_id,
            "strategy_id": strategy_id,
            "mode": "disabled",
        }
    if not skill_id or not strategy_id or not timeframe:
        reasons.append("backtest_gate_config_missing")
    if lookup_error:
        reasons.append("backtest_lookup_failed")
    if not latest_run_id:
        reasons.append("backtest_not_found")
    if not bool(skill_result.get("passed", False)):
        reasons.append("backtest_not_passed")
    if latest_run_id and not run:
        reasons.append("backtest_run_detail_missing")
    if run:
        if str(run.get("status") or "").lower() != "completed":
            reasons.append("backtest_run_not_completed")
        if str(run.get("skill_id") or "") != skill_id:
            reasons.append("backtest_skill_mismatch")
        if str(run.get("strategy_id") or "") != strategy_id:
            reasons.append("backtest_strategy_mismatch")
        if str(run.get("symbol") or "").upper() != symbol:
            reasons.append("backtest_symbol_mismatch")
        if str(run.get("timeframe") or "") != timeframe:
            reasons.append("backtest_timeframe_mismatch")

        timestamp = _parse_timestamp(
            run.get("updated_at")
            or run.get("created_at")
            or skill_result.get("updated_at")
        )
        if max_age_hours > 0:
            if timestamp is None:
                reasons.append("backtest_timestamp_missing")
            else:
                age_hours = max(
                    0.0,
                    (now - timestamp).total_seconds() / 3600.0,
                )
                if age_hours > max_age_hours:
                    reasons.append("backtest_stale")

    return {
        "symbol": symbol,
        "allowed": not reasons,
        "rejection_codes": sorted(set(reasons)),
        "latest_run_id": latest_run_id,
        "backtest_passed": bool(skill_result.get("passed", False)),
        "strategy_id": strategy_id,
        "run_symbol": run.get("symbol"),
        "run_strategy_id": run.get("strategy_id"),
        "run_timeframe": run.get("timeframe"),
        "mode": "required",
    }


def _combined_symbol_decision(
    *,
    symbol: str,
    attempts: List[Dict[str, Any]],
    details_by_strategy: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    allowed_attempts = [attempt for attempt in attempts if attempt.get("allowed")]
    if allowed_attempts:
        selected = max(
            allowed_attempts,
            key=lambda attempt: _detail_timestamp(
                details_by_strategy.get(str(attempt.get("strategy_id") or ""), {})
            ),
        )
        return {
            **selected,
            "selected_strategy_id": selected.get("strategy_id"),
            "attempted_strategy_ids": [
                attempt.get("strategy_id") for attempt in attempts
            ],
            "strategy_attempts": attempts,
        }

    latest_attempt = max(
        attempts,
        key=lambda attempt: _detail_timestamp(
            details_by_strategy.get(str(attempt.get("strategy_id") or ""), {})
        ),
        default={"symbol": symbol, "latest_run_id": None},
    )
    return {
        "symbol": symbol,
        "allowed": False,
        "rejection_codes": sorted(
            {
                code
                for attempt in attempts
                for code in (attempt.get("rejection_codes") or [])
            }
        ),
        "latest_run_id": latest_attempt.get("latest_run_id"),
        "backtest_passed": False,
        "selected_strategy_id": None,
        "attempted_strategy_ids": [
            attempt.get("strategy_id") for attempt in attempts
        ],
        "strategy_attempts": attempts,
        "mode": "required",
    }


async def filter_candidates_with_backtest_gate(
    *,
    db_client: Any,
    selected_positions: List[Dict[str, Any]],
    position_analysis_payloads: List[Dict[str, Any]],
    correlation_id: str,
    required: bool,
    skill_id: str,
    strategy_id: str,
    timeframe: str,
    max_age_hours: float,
    now: Optional[datetime] = None,
    strategy_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Keep candidates covered by their own exact latest passing Backtest.

    Each candidate is looked up by the complete execution-evidence identity.
    In multi-strategy mode the gate evaluates only the configured exact strategy
    IDs, then accepts the newest fresh passing result for that symbol. Missing,
    failed, stale, or mismatched evidence blocks only that symbol and can never
    fall back to another symbol or to the legacy fixed strategy.
    """

    symbols = list(
        dict.fromkeys(
            _symbol(position)
            for position in selected_positions
            if _symbol(position)
        )
    )
    resolved_strategy_ids = _configured_strategy_ids(
        primary_strategy_id=strategy_id,
        strategy_ids=strategy_ids,
    )
    evidence_by_key: Dict[tuple[str, str], Dict[str, Any]] = {
        (symbol, candidate_strategy_id): {}
        for symbol in symbols
        for candidate_strategy_id in resolved_strategy_ids
    }
    lookup_errors_by_key: Dict[tuple[str, str], str] = {}

    async def lookup(symbol: str, candidate_strategy_id: str) -> None:
        try:
            evidence_by_key[(symbol, candidate_strategy_id)] = (
                await db_client.get_latest_exact_backtest_run(
                    skill_id=skill_id,
                    strategy_id=candidate_strategy_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    correlation_id=correlation_id,
                )
            )
        except Exception as exc:
            lookup_errors_by_key[(symbol, candidate_strategy_id)] = str(exc)

    if required and symbols:
        await asyncio.gather(
            *(
                lookup(symbol, candidate_strategy_id)
                for symbol in symbols
                for candidate_strategy_id in resolved_strategy_ids
            )
        )

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    decisions: List[Dict[str, Any]] = []
    for position in selected_positions:
        symbol = _symbol(position)
        if not symbol:
            continue
        attempts = [
            _decision(
                symbol=symbol,
                required=required,
                detail=evidence_by_key.get((symbol, candidate_strategy_id), {}),
                skill_id=skill_id,
                strategy_id=candidate_strategy_id,
                timeframe=timeframe,
                max_age_hours=max_age_hours,
                now=current,
                lookup_error=lookup_errors_by_key.get(
                    (symbol, candidate_strategy_id)
                ),
            )
            for candidate_strategy_id in resolved_strategy_ids
        ]
        if not required:
            decisions.append(attempts[0])
            continue
        decisions.append(
            _combined_symbol_decision(
                symbol=symbol,
                attempts=attempts,
                details_by_strategy={
                    candidate_strategy_id: evidence_by_key.get(
                        (symbol, candidate_strategy_id), {}
                    )
                    for candidate_strategy_id in resolved_strategy_ids
                },
            )
        )

    allowed_symbols = {
        row["symbol"] for row in decisions if row.get("allowed")
    }
    allowed_positions = [
        row for row in selected_positions if _symbol(row) in allowed_symbols
    ]
    allowed_payloads = [
        row
        for row in position_analysis_payloads
        if _symbol(row) in allowed_symbols
    ]
    rejected = [row for row in decisions if not row.get("allowed")]
    lookup_errors = {
        (
            symbol
            if len(resolved_strategy_ids) == 1
            else f"{symbol}:{candidate_strategy_id}"
        ): error
        for (symbol, candidate_strategy_id), error in lookup_errors_by_key.items()
    }
    return {
        "status": "required" if required else "disabled",
        "required": required,
        "skill_id": skill_id,
        "strategy_id": (
            resolved_strategy_ids[0]
            if len(resolved_strategy_ids) == 1
            else None
        ),
        "strategy_ids": resolved_strategy_ids,
        "strategy_ids_by_symbol": {
            row["symbol"]: row.get("selected_strategy_id")
            for row in decisions
            if row.get("selected_strategy_id")
        },
        "timeframe": timeframe,
        "max_age_hours": max_age_hours,
        "latest_run_id": (
            decisions[0].get("latest_run_id")
            if len(decisions) == 1
            else None
        ),
        "latest_run_ids": {
            row["symbol"]: row.get("latest_run_id") for row in decisions
        },
        "lookup_error": (
            next(iter(lookup_errors.values()))
            if len(lookup_errors) == 1
            else None
        ),
        "lookup_errors": lookup_errors,
        "selected_positions": allowed_positions,
        "position_analysis_payloads": allowed_payloads,
        "decisions": decisions,
        "rejected": rejected,
        "summary": {
            "candidate_count": len(decisions),
            "allowed_count": len(decisions) - len(rejected),
            "rejected_count": len(rejected),
        },
    }
