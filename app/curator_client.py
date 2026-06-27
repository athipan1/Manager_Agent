from __future__ import annotations

from typing import Any, Dict, List

from . import config
from .logger import report_logger
from .resilient_client import AgentUnavailable, ResilientAgentClient


class CuratorAgentClient(ResilientAgentClient):
    """Client for Curator_Agent signal-only skill endpoints.

    Curator_Agent currently returns a lightweight response shape that is not the
    same as Manager's StandardAgentResponse contract, so this client intentionally
    returns raw response dictionaries after basic success checks.
    """

    def __init__(self):
        super().__init__(
            base_url=config.CURATOR_AGENT_URL,
            timeout=config.CURATOR_AGENT_TIMEOUT,
            max_retries=config.CURATOR_AGENT_MAX_RETRIES,
            failure_threshold=config.CURATOR_AGENT_FAILURE_THRESHOLD,
            cooldown_period=config.CURATOR_AGENT_COOLDOWN_SECONDS,
        )

    async def search_approved_skills(self, query: str, correlation_id: str) -> List[Dict[str, Any]]:
        response = await self._get(
            f"/skills/search?q={query}&approval_status=approved",
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
            "inputs": inputs,
            "timeout_seconds": timeout_seconds if timeout_seconds is not None else config.CURATOR_SKILL_TIMEOUT_SECONDS,
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
    if not config.CURATOR_AGENT_ENABLED:
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
