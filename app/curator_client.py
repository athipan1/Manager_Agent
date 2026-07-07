from __future__ import annotations

import os
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
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
_JSON_SCHEMA_NON_INPUT_KEYS = {"type", "properties", "required", "additionalProperties", "$schema", "title", "description"}


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


def _payload_value(payload: Dict[str, Any], *names: str) -> Optional[Any]:
    for name in names:
        value = payload.get(name)
        if value is not None:
            return value
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    for name in names:
        value = metadata.get(name)
        if value is not None:
            return value
    return None


def _analysis_score(analysis: Dict[str, Any]) -> Optional[Any]:
    score = _payload_value(analysis, "final_score", "final_opportunity_score", "candidate_score", "score")
    if score is not None:
        return score
    score_breakdown = analysis.get("score_breakdown") if isinstance(analysis.get("score_breakdown"), dict) else {}
    for name in ("final_opportunity_score", "final_score", "score"):
        value = score_breakdown.get(name)
        if value is not None:
            return value
    return None


def _skill_input_properties(skill: Dict[str, Any]) -> set[str]:
    input_schema = skill.get("input_schema")
    if not isinstance(input_schema, dict):
        return set()

    properties = input_schema.get("properties")
    if isinstance(properties, dict):
        return {str(name) for name in properties.keys()}

    legacy_names = {str(name) for name in input_schema.keys() if str(name) not in _JSON_SCHEMA_NON_INPUT_KEYS}
    return legacy_names


def _fallback_skill_input_names(skill: Dict[str, Any]) -> set[str]:
    name = str(skill.get("name") or "").lower()
    tags = {str(tag).lower() for tag in (skill.get("tags") or []) if tag is not None}

    if "manager advisory" in name:
        return {"symbol", "analysis", "ticker"}
    if "backtest" in name or "backtest" in tags or "score" in tags:
        return {"final_score"}
    return set()


def filter_skill_inputs_for_schema(skill: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Send only fields accepted by a Curator skill input contract.

    Curator expands `inputs` as keyword arguments. Some skills expose proper
    JSON Schema (`properties`) while older seeded skills expose a legacy mapping
    such as `{"final_score": "float"}`. If no schema is present in search or
    recommendation results, use conservative fallbacks by skill name/tags.
    """
    allowed = _skill_input_properties(skill) or _fallback_skill_input_names(skill)
    if not allowed:
        return dict(inputs)
    return {key: value for key, value in inputs.items() if key in allowed and value is not None}


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

    async def recommend_skills(
        self,
        *,
        account_id: str | int,
        symbol: str,
        analysis: Dict[str, Any],
        correlation_id: str,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        payload = {
            "account_id": account_id,
            "symbol": symbol.upper(),
            "asset_class": _payload_value(analysis, "asset_class") or "us_equity",
            "market_regime": _payload_value(analysis, "market_regime", "regime"),
            "strategy_bucket": _payload_value(analysis, "strategy_bucket"),
            "timeframe": _payload_value(analysis, "timeframe"),
            "top_k": top_k,
        }
        response = await self._post("/skills/recommend", correlation_id, json_data=json_safe_value(payload))
        if response.get("status") != "success":
            raise ValueError(response.get("error") or "Curator recommendation failed")
        data = response.get("data") or {}
        return data if isinstance(data, dict) else {}

    async def execute_skill(
        self,
        skill_id: str,
        *,
        inputs: Dict[str, Any],
        correlation_id: str,
        timeout_seconds: float | None = None,
        account_id: str | int = 1,
        symbol: Optional[str] = None,
        strategy_bucket: Optional[str] = None,
        market_regime: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "inputs": json_safe_value(inputs),
            "timeout_seconds": timeout_seconds if timeout_seconds is not None else CURATOR_SKILL_TIMEOUT_SECONDS,
            "account_id": account_id,
            "symbol": symbol,
            "strategy_bucket": strategy_bucket,
            "market_regime": market_regime,
            "run_id": run_id,
            "metadata": json_safe_value(metadata or {}),
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
    account_id: str | int = 1,
) -> Dict[str, Any]:
    """Fetch and execute one recommended Curator skill without breaking Manager flow."""
    if not CURATOR_AGENT_ENABLED:
        return {"status": "disabled", "reason": "CURATOR_AGENT_ENABLED=false"}

    try:
        async with CuratorAgentClient() as client:
            recommendation: Dict[str, Any] = {}
            try:
                if hasattr(client, "recommend_skills"):
                    recommendation = await client.recommend_skills(
                        account_id=account_id,
                        symbol=symbol,
                        analysis=analysis,
                        correlation_id=correlation_id,
                        top_k=3,
                    )
            except Exception as exc:
                recommendation = {"recommendation_state": "unavailable", "reason": str(exc)}

            skills = recommendation.get("recommended_skills") or []
            if not skills:
                skills = await client.search_approved_skills(f"{symbol} technical signal", correlation_id)
            if not skills:
                skills = await client.search_approved_skills("technical", correlation_id)
            if not skills:
                return {
                    "status": "no_skill",
                    "reason": "No approved or recommended Curator skills found.",
                    "recommendation": recommendation,
                }

            skill = skills[0]
            skill_id = str(skill.get("skill_id") or "")
            if not skill_id:
                return {"status": "invalid_skill", "reason": "Curator skill missing skill_id.", "skill": skill}

            strategy_bucket = _payload_value(analysis, "strategy_bucket")
            market_regime = _payload_value(analysis, "market_regime", "regime")
            candidate_inputs = {
                "symbol": symbol,
                "analysis": analysis,
                "ticker": symbol,
                "strategy_bucket": strategy_bucket,
                "market_regime": market_regime,
                "final_score": _analysis_score(analysis),
            }
            inputs = filter_skill_inputs_for_schema(skill, candidate_inputs)
            result = await client.execute_skill(
                skill_id,
                inputs=inputs,
                correlation_id=correlation_id,
                account_id=account_id,
                symbol=symbol,
                strategy_bucket=strategy_bucket,
                market_regime=market_regime,
                run_id=correlation_id,
                metadata={
                    "source_flow": "discover_analyze_trade",
                    "recommendation_state": recommendation.get("recommendation_state"),
                    "recommended_skill_score": skill.get("score"),
                    "filtered_input_keys": sorted(inputs.keys()),
                    "dropped_input_keys": sorted(set(candidate_inputs) - set(inputs)),
                },
            )
            return {
                "status": "success" if result.get("execution_status") == "success" else "failed",
                "skill_id": skill_id,
                "skill_name": skill.get("name"),
                "recommendation": recommendation,
                "selected_skill": skill,
                "execution": result,
            }
    except (AgentUnavailable, Exception) as exc:
        report_logger.warning(
            f"Curator signal unavailable for {symbol}: {exc}, correlation_id={correlation_id}"
        )
        return {"status": "unavailable", "reason": str(exc)}
