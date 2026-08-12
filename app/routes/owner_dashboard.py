from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..contracts.dashboard import DashboardSnapshot
from ..dashboard_routes import _dashboard_payload
from ..dashboard_security import enforce_dashboard_rate_limit
from .web_control import require_operator_token

router = APIRouter(prefix="/web-control", tags=["Web Control Center"])


@router.get("/owner-snapshot", response_model=DashboardSnapshot)
async def owner_snapshot(
    response: Response,
    account_id: Optional[str] = Query(default=None),
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
) -> DashboardSnapshot:
    """Return a full-value dashboard snapshot only to an authenticated operator.

    The public dashboard publisher remains masked. This endpoint is deliberately
    read-only and performs broker-state reads without reconciliation writes.
    """
    correlation_id = str(uuid.uuid4())
    try:
        payload = await _dashboard_payload(
            account_id,
            correlation_id,
            reconcile_broker=False,
        )
        from ..dashboard_snapshot import build_dashboard_snapshot

        snapshot = build_dashboard_snapshot(payload)
    except Exception as exc:
        # Do not expose service URLs, credentials, or upstream exception text.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Owner dashboard snapshot is temporarily unavailable.",
        ) from exc

    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Request-ID"] = correlation_id
    response.headers["X-Privacy-Mode"] = "owner-authenticated"
    return snapshot
