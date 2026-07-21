from __future__ import annotations

import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


DASHBOARD_SCHEMA_VERSION = "dashboard-snapshot.v1"


class DashboardContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DashboardAccount(DashboardContractModel):
    cash: float = 0.0
    equity: float = 0.0
    buyingPower: float = 0.0
    status: str = "UNKNOWN"
    mode: str = "UNKNOWN"
    lastSyncedAt: Optional[datetime.datetime] = None


class DashboardProtection(DashboardContractModel):
    status: str = "unknown"
    hasStopLoss: bool = False
    hasTakeProfit: bool = False
    hasBracket: bool = False


class DashboardPosition(DashboardContractModel):
    symbol: str
    quantity: float = 0.0
    averageCost: float = 0.0
    currentPrice: float = 0.0
    marketValue: float = 0.0
    unrealizedPnL: float = 0.0
    bucket: str = "unassigned"
    protection: DashboardProtection = Field(default_factory=DashboardProtection)


class DashboardOrder(DashboardContractModel):
    symbol: str
    side: str = "unknown"
    quantity: float = 0.0
    orderClass: str = "unknown"
    type: str = "unknown"
    status: str = "unknown"
    takeProfit: float = 0.0
    stopLoss: bool = False


class DashboardCuratorSignal(DashboardContractModel):
    symbol: str
    status: str = "unknown"
    skill: str = "Curator Signal"
    signal: str = "-"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class DashboardSummary(DashboardContractModel):
    positionCount: int = 0
    openOrderCount: int = 0
    curatorSignalCount: int = 0
    problemCount: int = 0
    dataSource: str = "unavailable"
    serviceStatus: Literal["OK", "DEGRADED"] = "DEGRADED"
    executionStatus: Optional[str] = None
    executionReason: Optional[str] = None


class DashboardSnapshot(DashboardContractModel):
    schemaVersion: Literal["dashboard-snapshot.v1"] = DASHBOARD_SCHEMA_VERSION
    generatedAt: datetime.datetime
    mode: str
    brokerMode: str
    flow: str = "portfolio_review"
    account: DashboardAccount
    positions: List[DashboardPosition] = Field(default_factory=list)
    openOrders: List[DashboardOrder] = Field(default_factory=list)
    curatorSignals: List[DashboardCuratorSignal] = Field(default_factory=list)
    summary: DashboardSummary


def dashboard_contract_json_schema() -> Dict[str, Any]:
    """Expose the exact public contract for documentation/tests."""
    return DashboardSnapshot.model_json_schema()
