"""Load the stdlib-only hourly runtime without importing the FastAPI package."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping


RUNTIME_PATH = Path(__file__).resolve().parents[1] / "app" / "hourly_paper_runtime.py"
runtime = sys.modules.get("app.hourly_paper_runtime")
if runtime is None:
    SPEC = importlib.util.spec_from_file_location(
        "manager_hourly_paper_runtime",
        RUNTIME_PATH,
    )
    if SPEC is None or SPEC.loader is None:
        raise RuntimeError("Unable to load the hourly Paper runtime module.")
    runtime = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = runtime
    sys.modules["app.hourly_paper_runtime"] = runtime
    SPEC.loader.exec_module(runtime)


# Market_Regime_Agent v0.2 enables API-key auth for production. The hourly
# Paper preflight must prove that secret exists before starting a trading stack.
if "MARKET_REGIME_API_KEY" not in runtime.SCHEDULED_REQUIRED_SECRETS:
    runtime.SCHEDULED_REQUIRED_SECRETS = (
        *runtime.SCHEDULED_REQUIRED_SECRETS,
        "MARKET_REGIME_API_KEY",
    )


_BaseJsonHttpClient = runtime.JsonHttpClient


def _performance_api_key() -> str:
    """Resolve the internal Performance_Agent key without exposing its value."""
    return (
        os.getenv("PERFORMANCE_AGENT_API_KEY")
        or os.getenv("PROFIT_AGENT_API_KEY")
        or ""
    ).strip()


def _market_regime_api_key() -> str:
    """Resolve the Market_Regime_Agent key used by the hourly runtime."""
    return (
        os.getenv("MARKET_REGIME_AGENT_API_KEY")
        or os.getenv("MARKET_REGIME_API_KEY")
        or ""
    ).strip()


def _safe_readiness_detail(raw: str) -> dict[str, Any]:
    """Extract only non-sensitive readiness fields from an upstream response."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    metadata = (
        payload.get("metadata")
        if isinstance(payload.get("metadata"), dict)
        else {}
    )
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    detail: dict[str, Any] = {
        "status": payload.get("status"),
        "ready": data.get("ready"),
        "failed_checks": metadata.get("failed_checks", []),
        "checks": data.get("checks", {}),
    }
    if error:
        detail["error"] = {
            "code": error.get("code"),
            "message": error.get("message"),
        }
    return detail


class HourlyJsonHttpClient(_BaseJsonHttpClient):
    """Hourly client with internal auth and safe readiness error diagnostics."""

    def __init__(
        self,
        base_url: str,
        service_name: str,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        effective_headers = dict(headers or {})
        if service_name == "Performance_Agent":
            api_key = _performance_api_key()
            if api_key:
                effective_headers.setdefault("X-API-KEY", api_key)
        if service_name == "Market_Regime_Agent":
            api_key = _market_regime_api_key()
            if api_key:
                effective_headers.setdefault("X-API-KEY", api_key)
        super().__init__(
            base_url,
            service_name,
            effective_headers,
            **kwargs,
        )

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Any = None,
        correlation_id: str,
    ) -> Any:
        try:
            return super().request(
                path,
                method=method,
                payload=payload,
                correlation_id=correlation_id,
            )
        except runtime.RuntimeSafetyError as exc:
            if self.service_name != "Performance_Agent" or path.rstrip("/") != "/ready":
                raise

            request_headers = {
                "Accept": "application/json",
                "X-Correlation-ID": correlation_id,
                **dict(self.headers or {}),
            }
            request = urllib.request.Request(
                f"{self.base_url.rstrip('/')}/ready",
                headers=request_headers,
                method="GET",
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as http_error:
                raw = http_error.read().decode("utf-8", errors="replace")
                detail = _safe_readiness_detail(raw)
                if detail:
                    safe_detail = json.dumps(
                        detail,
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                    raise runtime.RuntimeSafetyError(
                        f"{exc} readiness_detail={safe_detail}"
                    ) from exc
            raise


runtime.JsonHttpClient = HourlyJsonHttpClient

# Keep the core runtime stdlib-only while replacing the historical-data helper
# with the corrected explicit-lookback, paginated implementation used by the
# GitHub hourly entrypoint.
from scripts.hourly_market_regime_data import fetch_market_regime_inputs

runtime.fetch_market_regime_inputs = fetch_market_regime_inputs
