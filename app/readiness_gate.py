import datetime
from typing import Any, Dict, Optional

from . import config
from .alerts import alert_service
from .readiness_config import (
    READINESS_GATE_ENABLED,
    READINESS_GATE_FAIL_CLOSED,
    READINESS_GATE_MAX_AGE_SECONDS,
    READINESS_GATE_MIN_FUNDAMENTAL_CONFIDENCE,
    READINESS_GATE_MIN_FUNDAMENTAL_QUALITY,
    READINESS_GATE_TECH_MIN_TRAIN_BARS,
    READINESS_GATE_TECH_STEP_BARS,
    READINESS_GATE_TECH_TEST_BARS,
)
from .resilient_client import ResilientAgentClient


class ReadinessGateError(Exception):
    pass


def readiness_required() -> bool:
    return config.TRADING_MODE == "LIVE" or READINESS_GATE_ENABLED


def _parse_timestamp(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _is_fresh(timestamp: Optional[str], max_age_seconds: int = READINESS_GATE_MAX_AGE_SECONDS) -> bool:
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return False
    age = datetime.datetime.now(datetime.timezone.utc) - parsed
    return age.total_seconds() <= max_age_seconds


def _response_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data") or {}
    return data if isinstance(data, dict) else {}


def _report_result(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = _response_data(payload)
    passed = payload.get("status") == "success" and bool(data.get("passed"))
    fresh = _is_fresh(payload.get("timestamp"))
    return {
        "name": name,
        "status": payload.get("status"),
        "passed": passed,
        "fresh": fresh,
        "timestamp": payload.get("timestamp"),
        "data": data,
        "error": payload.get("error"),
    }


async def check_symbol_readiness(symbol: str, correlation_id: str) -> Dict[str, Any]:
    if not readiness_required():
        return {"required": False, "approved": True, "reason": "readiness_gate_disabled"}

    technical_payload = {
        "ticker": symbol,
        "timeframe": "1d",
        "min_train_bars": READINESS_GATE_TECH_MIN_TRAIN_BARS,
        "test_bars": READINESS_GATE_TECH_TEST_BARS,
        "step_bars": READINESS_GATE_TECH_STEP_BARS,
    }
    fundamental_payload = {
        "tickers": [symbol],
        "style": "growth",
        "min_data_quality_score": READINESS_GATE_MIN_FUNDAMENTAL_QUALITY,
        "min_average_confidence": READINESS_GATE_MIN_FUNDAMENTAL_CONFIDENCE,
    }

    try:
        async with ResilientAgentClient(config.TECHNICAL_AGENT_URL) as tech_client:
            technical = await tech_client._post("/validate/walk-forward", correlation_id, technical_payload)
        async with ResilientAgentClient(config.FUNDAMENTAL_AGENT_URL) as fund_client:
            fundamental = await fund_client._post("/validate/fundamental", correlation_id, fundamental_payload)
    except Exception as exc:
        alert_service.emit(
            "readiness_validation_unavailable",
            f"Readiness gate unavailable for {symbol}: {exc}",
            severity="critical",
            correlation_id=correlation_id,
            symbol=symbol,
            metadata={"error": str(exc)},
        )
        if READINESS_GATE_FAIL_CLOSED or config.TRADING_MODE == "LIVE":
            raise ReadinessGateError(f"readiness gate unavailable for {symbol}: {exc}") from exc
        return {"required": True, "approved": True, "reason": "readiness_gate_unavailable_fail_open", "error": str(exc)}

    technical_result = _report_result("technical_walk_forward", technical)
    fundamental_result = _report_result("fundamental_validation", fundamental)
    failures = []
    for item in [technical_result, fundamental_result]:
        if not item["passed"]:
            failures.append(f"{item['name']} did not pass")
        if not item["fresh"]:
            failures.append(f"{item['name']} report is stale or missing timestamp")

    approved = not failures
    readiness = {
        "required": True,
        "approved": approved,
        "reason": "validation_passed" if approved else "; ".join(failures),
        "technical": technical_result,
        "fundamental": fundamental_result,
        "max_age_seconds": READINESS_GATE_MAX_AGE_SECONDS,
    }
    alert_service.record_readiness_result(correlation_id=correlation_id, symbol=symbol, readiness=readiness)
    return readiness
