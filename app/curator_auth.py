from __future__ import annotations

import os
from typing import Dict


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_production() -> bool:
    environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development"))
    return environment.strip().lower() in {"production", "prod"}


CURATOR_AGENT_ENABLED = _env_bool("CURATOR_AGENT_ENABLED", False)
CURATOR_AGENT_API_KEY = os.getenv("CURATOR_AGENT_API_KEY", "").strip()
CURATOR_ADMIN_API_KEY = (
    os.getenv("CURATOR_ADMIN_API_KEY", "").strip() or CURATOR_AGENT_API_KEY
)

if _is_production() and CURATOR_AGENT_ENABLED and not CURATOR_AGENT_API_KEY:
    raise RuntimeError(
        "CURATOR_AGENT_API_KEY is required when Curator Agent is enabled in production."
    )


def curator_auth_headers(*, admin: bool = False) -> Dict[str, str]:
    """Return the role-appropriate Curator authentication header when configured."""

    api_key = CURATOR_ADMIN_API_KEY if admin else CURATOR_AGENT_API_KEY
    return {"X-API-KEY": api_key} if api_key else {}
