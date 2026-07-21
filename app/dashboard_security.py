from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, List

from fastapi import HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware


DEFAULT_DASHBOARD_ORIGINS = "http://localhost:5173"


def dashboard_cors_allowed_origins() -> List[str]:
    raw = os.getenv("DASHBOARD_CORS_ALLOWED_ORIGINS", DEFAULT_DASHBOARD_ORIGINS)
    origins = list(dict.fromkeys(value.strip() for value in raw.split(",") if value.strip()))
    environment = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")).strip().lower()
    if "*" in origins and environment in {"production", "prod"}:
        raise RuntimeError("DASHBOARD_CORS_ALLOWED_ORIGINS must not contain '*' in production.")
    return origins


def configure_dashboard_cors(app) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=dashboard_cors_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Request-ID"],
        expose_headers=["Cache-Control", "Retry-After", "X-Request-ID"],
        max_age=600,
    )


class DashboardRateLimiter:
    """Small per-process fixed-window limiter for the public read-only endpoint."""

    def __init__(self, limit: int = 120, window_seconds: int = 60):
        if limit < 1 or window_seconds < 1:
            raise ValueError("Dashboard rate limit and window must be positive.")
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        async with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (current - requests[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Dashboard request rate limit exceeded.",
                    headers={"Retry-After": str(retry_after)},
                )
            requests.append(current)

    async def reset(self) -> None:
        async with self._lock:
            self._requests.clear()


def _configured_rate_limiter() -> DashboardRateLimiter:
    try:
        limit = int(os.getenv("DASHBOARD_RATE_LIMIT_PER_MINUTE", "120"))
    except ValueError as exc:
        raise RuntimeError("DASHBOARD_RATE_LIMIT_PER_MINUTE must be an integer.") from exc
    return DashboardRateLimiter(limit=limit, window_seconds=60)


dashboard_rate_limiter = _configured_rate_limiter()


async def enforce_dashboard_rate_limit(request: Request) -> None:
    client_host = request.client.host if request.client else "unknown"
    await dashboard_rate_limiter.check(client_host)
