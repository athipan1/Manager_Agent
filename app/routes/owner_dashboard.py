from __future__ import annotations

import datetime as dt
import hmac
import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Any, Mapping

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response, status

from ..contracts.dashboard import (
    DashboardAccount,
    DashboardCuratorSignal,
    DashboardOrder,
    DashboardPosition,
    DashboardProtection,
    DashboardSnapshot,
    DashboardSummary,
)
from ..dashboard_security import enforce_dashboard_rate_limit
from .web_control import require_operator_token

router = APIRouter(prefix="/web-control", tags=["Web Control Center"])

STORE_SCHEMA_VERSION = "owner-snapshot-store.v1"
SOURCE_SCHEMA_VERSION = "dashboard-snapshot.v2"
FORBIDDEN_KEY_PARTS = (
    "authorization",
    "operator_token",
    "api_key",
    "secret_key",
    "password",
    "database_url",
)


def _store_path() -> Path:
    return Path(
        os.getenv(
            "OWNER_SNAPSHOT_STORE_PATH",
            "./config_data/latest-owner-dashboard-snapshot.json",
        )
    )


def _publisher_token() -> str:
    token = os.getenv("OWNER_SNAPSHOT_PUBLISH_TOKEN", "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Owner snapshot publisher is not configured.",
        )
    return token


async def require_snapshot_publisher(
    supplied: Annotated[str | None, Header(alias="X-Owner-Snapshot-Token")] = None,
) -> None:
    expected = _publisher_token()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid owner snapshot publisher token.",
        )


def _dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _timestamp(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Owner snapshot generatedAt is invalid.",
            ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(part in normalized for part in FORBIDDEN_KEY_PARTS):
                return True
            if _contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _position(row: Any) -> DashboardPosition | None:
    item = _dict(row)
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    protection = _dict(item.get("protection"))
    return DashboardPosition(
        symbol=symbol,
        quantity=_number(item.get("quantity")),
        averageCost=_number(item.get("averageCost")),
        currentPrice=_number(item.get("currentPrice")),
        marketValue=_number(item.get("marketValue")),
        unrealizedPnL=_number(item.get("unrealizedPnL")),
        bucket=str(item.get("bucket") or "unassigned"),
        protection=DashboardProtection(
            status=str(protection.get("status") or "unknown"),
            hasStopLoss=bool(protection.get("hasStopLoss", False)),
            hasTakeProfit=bool(protection.get("hasTakeProfit", False)),
            hasBracket=bool(protection.get("hasBracket", False)),
        ),
    )


def _order(row: Any) -> DashboardOrder | None:
    item = _dict(row)
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    return DashboardOrder(
        symbol=symbol,
        side=str(item.get("side") or "unknown"),
        quantity=_number(item.get("quantity")),
        orderClass=str(item.get("orderClass") or "unknown"),
        type=str(item.get("type") or "unknown"),
        status=str(item.get("status") or "unknown"),
        takeProfit=_number(item.get("takeProfit")),
        stopLoss=bool(item.get("stopLoss", False)),
    )


def _signal(row: Any) -> DashboardCuratorSignal | None:
    item = _dict(row)
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    return DashboardCuratorSignal(
        symbol=symbol,
        status=str(item.get("status") or "unknown"),
        skill=str(item.get("skill") or "Curator Signal"),
        signal=str(item.get("signal") or "-"),
        confidence=max(0.0, min(1.0, _number(item.get("confidence")))),
    )


def _snapshot_from_github(payload: Mapping[str, Any]) -> tuple[DashboardSnapshot, int | None]:
    if payload.get("schemaVersion") != SOURCE_SCHEMA_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported owner snapshot schema.",
        )
    if _contains_forbidden_key(payload):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Owner snapshot contains forbidden secret fields.",
        )

    privacy = _dict(payload.get("privacy"))
    account = _dict(payload.get("account"))
    if privacy.get("mode") != "full" or privacy.get("valuesMasked") is not False:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Owner snapshot must use full privacy mode.",
        )
    if account.get("valuesMasked") is not False:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Owner account values must be unmasked.",
        )
    if all(account.get(key) is None for key in ("cash", "equity", "buyingPower")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Owner snapshot does not contain account values.",
        )

    runtime = _dict(payload.get("runtime"))
    workflow = _dict(payload.get("workflow"))
    raw_summary = _dict(payload.get("summary"))
    generated_at = _timestamp(payload.get("generatedAt"))
    positions = [item for row in _list(payload.get("positions")) if (item := _position(row)) is not None]
    orders = [item for row in _list(payload.get("openOrders")) if (item := _order(row)) is not None]
    signals = [item for row in _list(payload.get("signals")) if (item := _signal(row)) is not None]
    degraded = bool(payload.get("error")) or str(workflow.get("conclusion") or "").lower() not in {
        "success",
        "completed",
        "neutral",
    }

    snapshot = DashboardSnapshot(
        generatedAt=generated_at,
        mode=str(runtime.get("mode") or "PAPER"),
        brokerMode=str(runtime.get("brokerMode") or "ALPACA"),
        flow=str(runtime.get("flow") or "hourly_portfolio_cycle"),
        account=DashboardAccount(
            cash=_number(account.get("cash")),
            equity=_number(account.get("equity")),
            buyingPower=_number(account.get("buyingPower")),
            status=str(account.get("status") or "ACTIVE"),
            mode=str(runtime.get("mode") or "PAPER"),
            lastSyncedAt=_timestamp(account.get("lastSyncedAt") or payload.get("generatedAt")),
        ),
        positions=positions,
        openOrders=orders,
        curatorSignals=signals,
        summary=DashboardSummary(
            positionCount=len(positions),
            openOrderCount=len(orders),
            curatorSignalCount=len(signals),
            problemCount=1 if degraded else 0,
            dataSource="github-actions-owner-snapshot",
            serviceStatus="DEGRADED" if degraded else "OK",
            executionStatus=raw_summary.get("executionStatus"),
            executionReason=raw_summary.get("executionReason"),
        ),
    )

    run_id = workflow.get("runId")
    try:
        parsed_run_id = int(run_id) if run_id is not None else None
    except (TypeError, ValueError):
        parsed_run_id = None
    return snapshot, parsed_run_id


def _read_store() -> dict[str, Any]:
    path = _store_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No GitHub Actions owner snapshot has been published yet.",
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored owner snapshot is unavailable.",
        ) from exc
    if value.get("schemaVersion") != STORE_SCHEMA_VERSION or not isinstance(value.get("snapshot"), dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored owner snapshot is unavailable.",
        )
    return value


def _write_store(snapshot: DashboardSnapshot, workflow_run_id: int | None) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schemaVersion": STORE_SCHEMA_VERSION,
        "source": "github-actions",
        "workflowRunId": workflow_run_id,
        "publishedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "snapshot": snapshot.model_dump(mode="json"),
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


@router.post("/owner-snapshot/publish")
async def publish_owner_snapshot(
    payload: Annotated[dict[str, Any], Body()],
    _: None = Depends(require_snapshot_publisher),
    __: None = Depends(enforce_dashboard_rate_limit),
) -> dict[str, Any]:
    """Persist a full-value snapshot created by the trusted GitHub Actions pipeline."""
    snapshot, workflow_run_id = _snapshot_from_github(payload)

    try:
        current = _read_store()
    except HTTPException as exc:
        if exc.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
            raise
        current = {}

    current_run_id = current.get("workflowRunId")
    if (
        isinstance(current_run_id, int)
        and workflow_run_id is not None
        and workflow_run_id < current_run_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Refusing to replace the owner snapshot with an older workflow run.",
        )

    _write_store(snapshot, workflow_run_id)
    return {
        "status": "stored",
        "source": "github-actions",
        "workflowRunId": workflow_run_id,
        "generatedAt": snapshot.generatedAt,
    }


@router.get("/owner-snapshot", response_model=DashboardSnapshot)
async def owner_snapshot(
    response: Response,
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
) -> DashboardSnapshot:
    """Return the latest full-value snapshot published by GitHub Actions.

    This endpoint is deliberately read-only. It never contacts Execution_Agent,
    Alpaca, Database_Agent, or any other trading dependency at request time.
    """
    stored = _read_store()
    try:
        snapshot = DashboardSnapshot.model_validate(stored["snapshot"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored owner snapshot is unavailable.",
        ) from exc

    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Request-ID"] = str(uuid.uuid4())
    response.headers["X-Privacy-Mode"] = "owner-authenticated"
    response.headers["X-Owner-Snapshot-Source"] = "github-actions"
    if stored.get("workflowRunId") is not None:
        response.headers["X-Owner-Snapshot-Run-ID"] = str(stored["workflowRunId"])
    return snapshot
