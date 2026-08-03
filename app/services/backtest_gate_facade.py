"""Compatibility façade for the Backtest execution gate.

Production execution uses Database_Agent promotion authority. The previous raw
Backtest validator remains available only when promotion authority is explicitly
disabled, which preserves diagnostic and migration tests without allowing raw
metadata to authorize production execution.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, List, Optional, Union

from .. import config
from .promotion_execution_gate import filter_candidates_with_promotion_gate
from .promotion_paper_observer import observe_promotion_gate_result


_LEGACY_MODULE_NAME = "app.services._legacy_backtest_execution_gate"
_existing_legacy = sys.modules.get(_LEGACY_MODULE_NAME)
if _existing_legacy is None:
    legacy_path = Path(__file__).with_name("backtest_execution_gate.py")
    spec = importlib.util.spec_from_file_location(_LEGACY_MODULE_NAME, legacy_path)
    if spec is None or spec.loader is None:
        raise ImportError("Unable to load legacy Backtest gate compatibility module")
    _legacy: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[_LEGACY_MODULE_NAME] = _legacy
    spec.loader.exec_module(_legacy)
else:
    _legacy = _existing_legacy

LEGACY_WALK_FORWARD_VALIDATION_PROFILE = (
    _legacy.LEGACY_WALK_FORWARD_VALIDATION_PROFILE
)
NESTED_WALK_FORWARD_VALIDATION_PROFILE = (
    _legacy.NESTED_WALK_FORWARD_VALIDATION_PROFILE
)
WALK_FORWARD_VALIDATION_PROFILE = _legacy.WALK_FORWARD_VALIDATION_PROFILE
SUPPORTED_WALK_FORWARD_VALIDATION_PROFILES = (
    _legacy.SUPPORTED_WALK_FORWARD_VALIDATION_PROFILES
)
NESTED_SELECTION_METHOD = _legacy.NESTED_SELECTION_METHOD


def _authority_required(value: Optional[bool]) -> bool:
    if value is not None:
        return value
    configured = getattr(config, "BACKTEST_PROMOTION_AUTHORITY_REQUIRED", None)
    if configured is not None:
        return bool(configured)
    return bool(config.BACKTEST_EXECUTION_GATE_REQUIRED)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _observation_required(
    value: Optional[bool],
    *,
    authority_required: bool,
) -> bool:
    if value is not None:
        return value
    configured = os.getenv("BACKTEST_PROMOTION_OBSERVATION_REQUIRED")
    if configured is not None:
        return _env_bool("BACKTEST_PROMOTION_OBSERVATION_REQUIRED")
    environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development"))
    return authority_required and environment.strip().lower() in {
        "production",
        "prod",
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
    now: Any = None,
    strategy_ids: Optional[Iterable[str]] = None,
    walk_forward_required: Optional[bool] = None,
    promotion_authority_required: Optional[bool] = None,
    paper_observation_required: Optional[bool] = None,
    account_id: Optional[Union[int, str]] = None,
    auto_approve: Optional[bool] = None,
    execution_client: Any = None,
) -> Dict[str, Any]:
    authority_required = _authority_required(promotion_authority_required)
    if not authority_required:
        return await _legacy.filter_candidates_with_backtest_gate(
            db_client=db_client,
            selected_positions=selected_positions,
            position_analysis_payloads=position_analysis_payloads,
            correlation_id=correlation_id,
            required=required,
            skill_id=skill_id,
            strategy_id=strategy_id,
            timeframe=timeframe,
            max_age_hours=max_age_hours,
            now=now,
            strategy_ids=strategy_ids,
            walk_forward_required=walk_forward_required,
        )

    gate_result = await filter_candidates_with_promotion_gate(
        db_client=db_client,
        selected_positions=selected_positions,
        position_analysis_payloads=position_analysis_payloads,
        correlation_id=correlation_id,
        required=required,
        skill_id=skill_id,
        strategy_id=strategy_id,
        timeframe=timeframe,
        max_age_hours=max_age_hours,
        now=now,
        strategy_ids=strategy_ids,
        walk_forward_required=walk_forward_required,
        account_id=account_id,
        auto_approve=auto_approve,
    )
    observation_required = _observation_required(
        paper_observation_required,
        authority_required=authority_required,
    )
    if not required or not observation_required:
        return {
            **gate_result,
            "paper_observation": {
                "status": "disabled" if not observation_required else "not_required",
                "required": observation_required,
                "reason": (
                    "paper_observation_disabled"
                    if not observation_required
                    else "backtest_gate_disabled"
                ),
            },
        }

    resolved_account_id = str(
        gate_result.get("account_id")
        or account_id
        or config.DEFAULT_ACCOUNT_ID
    )
    return await observe_promotion_gate_result(
        db_client=db_client,
        gate_result=gate_result,
        account_id=resolved_account_id,
        correlation_id=correlation_id,
        execution_client=execution_client,
    )


__all__ = [
    "LEGACY_WALK_FORWARD_VALIDATION_PROFILE",
    "NESTED_WALK_FORWARD_VALIDATION_PROFILE",
    "WALK_FORWARD_VALIDATION_PROFILE",
    "SUPPORTED_WALK_FORWARD_VALIDATION_PROFILES",
    "NESTED_SELECTION_METHOD",
    "filter_candidates_with_backtest_gate",
]
