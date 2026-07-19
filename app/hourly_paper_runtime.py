"""Fail-closed runtime contract for the hourly Alpaca Paper workflow.

This module intentionally has no third-party dependencies so GitHub Actions can
validate the scheduled runtime before building or starting Execution_Agent.
Secret values are never included in returned diagnostics or exception text.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


PAPER_API_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_API_URL = "https://data.alpaca.markets"
PLACEHOLDER_SECRETS = {
    "changeme",
    "dev_database_key",
    "dev_execution_key",
    "dev_portfolio_key",
    "password",
    "secret",
    "test",
}
SCHEDULED_REQUIRED_SECRETS = (
    "ALPACA_API_KEY_ID",
    "ALPACA_SECRET_KEY",
    "ALPACA_API_URL",
    "EXECUTION_API_KEY",
    "DATABASE_AGENT_URL",
    "DATABASE_AGENT_API_KEY",
    "RISK_ADMIN_TOKEN",
    "PORTFOLIO_AGENT_API_KEY",
)
REQUIRED_SCHEDULED_FLAGS = {
    "TRADING_ENABLED": "true",
    "TRADING_MODE": "PAPER",
    "BROKER_MODE": "ALPACA",
    "DRY_RUN": "false",
    "ALLOW_LIVE_TRADING": "false",
    "BACKTEST_EXECUTION_GATE_REQUIRED": "true",
    "BROKER_RECONCILE_REQUIRED": "true",
    "BROKER_RECONCILE_CONTEXT_REQUIRED": "true",
    "PERFORMANCE_SESSION_RISK_REQUIRED": "true",
}


class RuntimeSafetyError(RuntimeError):
    """Raised when the automated runtime cannot prove Paper-only safety."""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _bool_text(value: Any) -> str:
    return _clean(value).lower()


def is_placeholder_secret(value: Any) -> bool:
    normalized = _clean(value).lower()
    return (
        not normalized
        or normalized in PLACEHOLDER_SECRETS
        or normalized.startswith("dev_")
        or normalized.startswith("replace_me")
    )


def _validate_https_service_url(value: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeSafetyError(
            "DATABASE_AGENT_URL must be a credential-free HTTPS service URL."
        )
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        raise RuntimeSafetyError(
            "Scheduled Paper runtime must use the remote Railway Database_Agent."
        )


def validate_runtime_environment(
    environ: Mapping[str, str] | None = None,
    *,
    event_name: str | None = None,
) -> dict[str, Any]:
    """Validate runtime flags and secrets without returning secret material."""
    env = dict(os.environ if environ is None else environ)
    event = _clean(event_name or env.get("GITHUB_EVENT_NAME") or "local")
    scheduled = event == "schedule"
    broker_mode = _clean(env.get("BROKER_MODE") or "SIMULATOR").upper()
    dry_run = _bool_text(env.get("DRY_RUN") or "true") != "false"
    paper_automation = scheduled or (broker_mode == "ALPACA" and not dry_run)

    if scheduled:
        for name, expected in REQUIRED_SCHEDULED_FLAGS.items():
            actual = _clean(env.get(name))
            if actual.upper() != expected.upper():
                raise RuntimeSafetyError(
                    f"Scheduled Paper safety requires {name}={expected}."
                )

    if _bool_text(env.get("ALLOW_LIVE_TRADING") or "false") != "false":
        raise RuntimeSafetyError("ALLOW_LIVE_TRADING must remain false.")
    if _clean(env.get("TRADING_MODE") or "PAPER").upper() != "PAPER":
        raise RuntimeSafetyError("Only TRADING_MODE=PAPER is allowed.")
    if broker_mode not in {"ALPACA", "SIMULATOR"}:
        raise RuntimeSafetyError("BROKER_MODE must be ALPACA or SIMULATOR.")
    if broker_mode == "SIMULATOR" and not dry_run:
        raise RuntimeSafetyError("Simulator runtime must keep DRY_RUN=true.")

    if paper_automation:
        for name in SCHEDULED_REQUIRED_SECRETS:
            value = env.get(name)
            if name.endswith("_URL"):
                if not _clean(value):
                    raise RuntimeSafetyError(f"Missing required secret: {name}.")
                continue
            if is_placeholder_secret(value):
                raise RuntimeSafetyError(
                    f"Missing or placeholder value for required secret: {name}."
                )

        if _clean(env.get("ALPACA_API_URL")) != PAPER_API_URL:
            raise RuntimeSafetyError(
                "ALPACA_API_URL must exactly match the Alpaca Paper endpoint."
            )
        _validate_https_service_url(_clean(env.get("DATABASE_AGENT_URL")))

    return {
        "event_name": event,
        "scheduled": scheduled,
        "paper_automation": paper_automation,
        "broker_mode": broker_mode,
        "dry_run": dry_run,
        "trading_mode": "PAPER",
        "allow_live_trading": False,
        "paper_api_url_valid": (
            not paper_automation
            or _clean(env.get("ALPACA_API_URL")) == PAPER_API_URL
        ),
        "required_secret_names": (
            list(SCHEDULED_REQUIRED_SECRETS) if paper_automation else []
        ),
    }


def deterministic_portfolio_cycle_id(
    *,
    account_id: str,
    utc_hour: datetime | None = None,
) -> str:
    """Return a stable, non-sensitive identity for one account and UTC hour."""
    hour = (utc_hour or datetime.now(timezone.utc)).astimezone(timezone.utc)
    account_hash = hashlib.sha256(_clean(account_id).encode("utf-8")).hexdigest()[:12]
    hour_text = hour.strftime("%Y%m%dT%H")
    return f"hourly-paper-{account_hash}-{hour_text}"


def deterministic_order_idempotency_key(
    *,
    portfolio_cycle_id: str,
    account_id: str,
    symbol: str,
    side: str,
    strategy_id: str,
    position_lifecycle_id: str,
) -> str:
    identity = "|".join(
        (
            _clean(portfolio_cycle_id),
            _clean(account_id),
            _clean(symbol).upper(),
            _clean(side).lower(),
            _clean(strategy_id),
            _clean(position_lifecycle_id),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"hourly-paper-{digest[:32]}"


@dataclass
class JsonHttpClient:
    """Small bounded-retry JSON client that never includes base URLs in errors."""

    base_url: str
    service_name: str
    headers: Mapping[str, str] | None = None
    timeout_seconds: float = 10.0
    max_attempts: int = 3

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Any = None,
        correlation_id: str,
    ) -> Any:
        request_headers = {
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
            **dict(self.headers or {}),
        }
        body = None
        if payload is not None:
            body = json.dumps(payload, default=str).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        last_error = "request failed"
        for attempt in range(1, max(1, self.max_attempts) + 1):
            request = urllib.request.Request(
                f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
                data=body,
                headers=request_headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                if exc.code < 500:
                    break
            except Exception as exc:  # URL and credentials are intentionally omitted
                last_error = type(exc).__name__
            if attempt < self.max_attempts:
                time.sleep(min(2 ** (attempt - 1), 2))
        raise RuntimeSafetyError(
            f"{self.service_name} {method} {path} failed after bounded retries: "
            f"{last_error}."
        )


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data")
    return payload


def check_railway_database(
    *,
    base_url: str,
    api_key: str,
    correlation_id: str,
) -> dict[str, Any]:
    client = JsonHttpClient(
        base_url=base_url,
        service_name="Railway Database_Agent",
        headers={"X-API-KEY": api_key},
    )
    health_response = client.request("/health", correlation_id=correlation_id)
    ready_response = client.request("/ready", correlation_id=correlation_id)
    version_response = client.request("/version", correlation_id=correlation_id)
    health = _unwrap(health_response) or {}
    ready = _unwrap(ready_response) or {}
    version = _unwrap(version_response) or {}

    if not isinstance(health, dict) or health.get("database_connection") != "connected":
        raise RuntimeSafetyError(
            "Railway Database_Agent health did not confirm PostgreSQL connectivity."
        )
    if health.get("dev_mode") is not False:
        raise RuntimeSafetyError(
            "Railway Database_Agent must have DATABASE_DEV_MODE=false."
        )
    if _clean(health.get("trading_mode")).upper() != "PAPER":
        raise RuntimeSafetyError(
            "Railway Database_Agent did not report TRADING_MODE=PAPER."
        )
    if health.get("database_emergency_halt") is True:
        raise RuntimeSafetyError("Railway Database_Agent emergency halt is active.")
    if not isinstance(ready, dict) or ready.get("ready") is not True:
        raise RuntimeSafetyError("Railway Database_Agent readiness check failed.")
    if ready.get("dev_mode") is not False:
        raise RuntimeSafetyError("Railway Database_Agent readiness reports dev mode.")
    if ready.get("database_agent_api_key_configured") is not True:
        raise RuntimeSafetyError(
            "Railway Database_Agent does not report an API key configuration."
        )
    if not isinstance(version, dict) or _clean(version.get("agent_type")) != "database":
        raise RuntimeSafetyError("Railway Database_Agent version contract is invalid.")

    return {
        "health": "connected",
        "ready": True,
        "dev_mode": False,
        "trading_mode": "PAPER",
        "version": _clean(version.get("version")),
        "schema_version": _clean(version.get("schema_version")),
    }


def check_alpaca_paper(
    *,
    api_url: str,
    api_key_id: str,
    secret_key: str,
    correlation_id: str,
) -> dict[str, Any]:
    if api_url != PAPER_API_URL:
        raise RuntimeSafetyError("Refusing to contact a non-Paper Alpaca endpoint.")
    client = JsonHttpClient(
        base_url=api_url,
        service_name="Alpaca Paper",
        headers={
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": secret_key,
        },
    )
    account = client.request("/v2/account", correlation_id=correlation_id)
    clock = client.request("/v2/clock", correlation_id=correlation_id)
    if not isinstance(account, dict) or not _clean(account.get("id")):
        raise RuntimeSafetyError("Alpaca Paper account response is invalid.")
    if not isinstance(clock, dict) or not isinstance(clock.get("is_open"), bool):
        raise RuntimeSafetyError("Alpaca Paper market clock response is invalid.")

    restricted = any(
        account.get(name) is True
        for name in ("trading_blocked", "account_blocked", "transfers_blocked")
    )
    account_active = _clean(account.get("status")).upper() == "ACTIVE" and not restricted
    market_open = bool(clock["is_open"])
    market_mode = (
        "BLOCKED"
        if not account_active
        else "REVIEW_AND_TRADE"
        if market_open
        else "PORTFOLIO_REVIEW_ONLY"
    )
    return {
        "account_id": _clean(account["id"]),
        "account_status": _clean(account.get("status")),
        "account_active": account_active,
        "restricted": restricted,
        "market_open": market_open,
        "market_mode": market_mode,
        "clock_timestamp": clock.get("timestamp"),
        "next_open": clock.get("next_open"),
        "next_close": clock.get("next_close"),
    }


def fetch_market_regime_inputs(
    *,
    api_key_id: str,
    secret_key: str,
    correlation_id: str,
    symbol: str = "SPY",
) -> dict[str, Any]:
    """Fetch daily Alpaca bars and derive deterministic Market_Regime inputs."""
    client = JsonHttpClient(
        base_url=ALPACA_DATA_API_URL,
        service_name="Alpaca Market Data",
        headers={
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": secret_key,
        },
        timeout_seconds=20,
    )
    payload = client.request(
        f"/v2/stocks/{symbol}/bars?timeframe=1Day&limit=220&adjustment=raw&feed=iex&sort=asc",
        correlation_id=correlation_id,
    )
    bars = payload.get("bars") if isinstance(payload, dict) else None
    if not isinstance(bars, list) or len(bars) < 200:
        raise RuntimeSafetyError(
            "Alpaca Market Data did not return enough bars for Market_Regime_Agent."
        )
    closes = [float(row["c"]) for row in bars if row.get("c") is not None]
    if len(closes) < 200:
        raise RuntimeSafetyError("Market regime close-price history is incomplete.")
    true_ranges: list[float] = []
    previous_close: float | None = None
    for row in bars[-15:]:
        high = float(row["h"])
        low = float(row["l"])
        close = float(row["c"])
        true_ranges.append(
            high - low
            if previous_close is None
            else max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
        previous_close = close
    price = closes[-1]
    atr = sum(true_ranges[-14:]) / max(1, len(true_ranges[-14:]))
    return {
        "symbol": symbol,
        "price": round(price, 6),
        "sma_50": round(sum(closes[-50:]) / 50, 6),
        "sma_200": round(sum(closes[-200:]) / 200, 6),
        "atr_pct": round(atr / price, 8) if price > 0 else None,
    }
