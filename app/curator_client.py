from __future__ import annotations

import os
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List
from urllib.parse import quote

from .logger import report_logger
from .resilient_client import AgentUnavailable, ResilientAgentClient


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


CURATOR_AGENT_URL = os.getenv("CURATOR_AGENT_URL", "http://curator-agent:8010")
CURATOR_AGENT_ENABLED = _env_bool("CURATOR_AGENT_ENABLED", False)
CURATOR_AGENT_TIMEOUT = _env_float("CURATOR_AGENT_TIMEOUT", 5.0)
CURATOR_AGENT_MAX_RETRIES = _env_int("CURATOR_AGENT_MAX_RETRIES", 1)
CURATOR_AGENT_FAILURE_THRESHOLD = _env_int("CURATOR_AGENT_FAILURE_THRESHOLD", 2)
CURATOR_AGENT_COOLDOWN_SECONDS = _env_int("CURATOR_AGENT_COOLDOWN_SECONDS", 30)
CURATOR_SKILL_TIMEOUT_SECONDS = _env_float("CURATOR_SKILL_TIMEOUT_SECONDS", 1.0)


def json_safe_value(value: Any) -> Any:
    """Convert Manager payload values into JSON-safe data for Curator.

    Curator skill execution is advisory-only and travels over JSON. Some
    Manager analysis payloads can contain Pydantic models or agent DTO objects,
    so sanitize a copy before sending it to Curator. The original payload used
    by Risk/Execution remains unchanged.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe_value(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return json_safe_value(value.model_dump(mode="json"))
        except TypeError:
            return json_safe_value(value.model_dump())
    if hasattr(value, "dict"):
        try:
            return json_safe_value(value.dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        public_fields = {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
        if public_fields:
            return json_safe_value(public_fields)
    return str(value)


class CuratorAgentClient(ResilientAgentClient):
    """Client for Curator_Agent signal-only skill endpoints.

    Curator_Agent returns a lightweight response shape that is not the same as
    Manager's StandardAgentResponse contract, so this client intentionally
    returns raw response dictionaries after basic success checks.
    """

    def __init__(self):
        super().__init__(
            base_url=CURATOR_AGENT_URL,
            timeout=CURATOR_AGENT_TIMEOUT,
            max_retries=CURATOR_AGENT_MAX_RETRIES,
            failure_threshold=CURATOR_AGENT_FAILURE_THRESHOLD,
            cooldown_period=CURATOR_AGENT_COOLDOWN_SECONDS,
        )

    async def search_approved_skills(self, query: str, correlation_id: str) -> List[Dict[str, Any]]:
        response = await self._get(
            f"/skills/search?q={quote(query)}&approval_status=approved",
            correlation_id,
        )
        if response.get("status") != "success":
            raise ValueError(response.get("error") or "Curator search failed")
        data = response.get("data") or []
        return data if isinstance(data, list) else []

    async def execute_skill(
        self,
        skill_id: str,
        *,
        inputs: Dict[str, Any],
        correlation_id: str,
        timeout_seconds: float | None = None,
    ) -> Dict[str, Any]:
        payload = {
            "inputs": json_safe_value(inputs),
            "timeout_seconds": timeout_seconds if timeout_seconds is not None else CURATOR_SKILL_TIMEOUT_SECONDS,
        }
        response = await self._post(f"/skills/{skill_id}/execute", correlation_id, json_data=payload)
        if response.get("status") != "success":
            raise ValueError(response.get("error") or "Curator execute failed")
        data = response.get("data") or {}
        return data if isinstance(data, dict) else {}


async def best_effort_curator_signal(
    *,
    symbol: str,
    analysis: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
    """Fetch and execute one approved Curator skill without breaking Manager flow.

    This is intentionally best-effort. If Curator is down, unconfigured, or a
    skill fails, Manager records diagnostics and continues with its original
    Technical/Fundamental/Risk/Execution path.
    """
    if not CURATOR_AGENT_ENABLED:
        return {"status": "disabled", "reason": "CURATOR_AGENT_ENABLED=false"}

    try:
        async with CuratorAgentClient() as client:
            query = f"{symbol} technical signal"
            skills = await client.search_approved_skills(query, correlation_id)
            if not skills:
                skills = await client.search_approved_skills("technical", correlation_id)
            if not skills:
                return {"status": "no_skill", "reason": "No approved Curator skills found."}

            skill = skills[0]
            skill_id = str(skill.get("skill_id") or "")
            if not skill_id:
                return {"status": "invalid_skill", "reason": "Approved skill missing skill_id.", "skill": skill}

            result = await client.execute_skill(
                skill_id,
                inputs={
                    "symbol": symbol,
                    "analysis": analysis,
                    "ticker": symbol,
                },
                correlation_id=correlation_id,
            )
            return {
                "status": "success" if result.get("execution_status") == "success" else "failed",
                "skill_id": skill_id,
                "skill_name": skill.get("name"),
                "execution": result,
            }
    except (AgentUnavailable, Exception) as exc:
        report_logger.warning(
            f"Curator signal unavailable for {symbol}: {exc}, correlation_id={correlation_id}"
        )
        return {"status": "unavailable", "reason": str(exc)}
