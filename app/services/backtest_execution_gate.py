"""Fail-closed Backtest gate for Manager execution candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


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


def _decision(
    *,
    symbol: str,
    required: bool,
    status: Dict[str, Any],
    detail: Dict[str, Any],
    skill_id: str,
    strategy_id: str,
    timeframe: str,
    max_age_hours: float,
    now: datetime,
    lookup_error: Optional[str],
) -> Dict[str, Any]:
    run = detail.get("run") if isinstance(detail.get("run"), dict) else {}
    latest_run_id = status.get("latest_run_id")
    reasons: List[str] = []

    if not required:
        return {
            "symbol": symbol,
            "allowed": True,
            "rejection_codes": [],
            "latest_run_id": latest_run_id,
            "mode": "disabled",
        }
    if not skill_id or not strategy_id or not timeframe:
        reasons.append("backtest_gate_config_missing")
    if lookup_error:
        reasons.append("backtest_lookup_failed")
    if not latest_run_id:
        reasons.append("backtest_not_found")
    if not bool(status.get("passed", False)):
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
            or status.get("updated_at")
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
        "backtest_passed": bool(status.get("passed", False)),
        "run_symbol": run.get("symbol"),
        "run_strategy_id": run.get("strategy_id"),
        "run_timeframe": run.get("timeframe"),
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
) -> Dict[str, Any]:
    """Keep only candidates covered by the exact latest passing Backtest run.

    Database_Agent currently exposes one latest run per skill. Therefore the
    latest run must match every execution candidate explicitly; a passing run
    for another symbol, strategy, or timeframe never authorizes an order.
    """
    status: Dict[str, Any] = {}
    detail: Dict[str, Any] = {}
    lookup_error: Optional[str] = None
    if required:
        try:
            status = await db_client.get_skill_backtest_status(
                skill_id,
                correlation_id,
            )
            latest_run_id = status.get("latest_run_id")
            if latest_run_id:
                detail = await db_client.get_backtest_run(
                    str(latest_run_id),
                    correlation_id,
                )
        except Exception as exc:
            lookup_error = str(exc)

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    decisions = [
        _decision(
            symbol=_symbol(position),
            required=required,
            status=status,
            detail=detail,
            skill_id=skill_id,
            strategy_id=strategy_id,
            timeframe=timeframe,
            max_age_hours=max_age_hours,
            now=current,
            lookup_error=lookup_error,
        )
        for position in selected_positions
        if _symbol(position)
    ]
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
    return {
        "status": "required" if required else "disabled",
        "required": required,
        "skill_id": skill_id,
        "strategy_id": strategy_id,
        "timeframe": timeframe,
        "max_age_hours": max_age_hours,
        "latest_run_id": status.get("latest_run_id"),
        "lookup_error": lookup_error,
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
