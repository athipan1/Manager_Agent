import datetime
import os
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Deque, Dict, List, Optional
from uuid import uuid4

from .logger import report_logger


_ALERTS_MAX_EVENTS = int(os.getenv("ALERTS_MAX_EVENTS", "500"))
_APPROVAL_REJECT_SPIKE_THRESHOLD = int(os.getenv("ALERT_APPROVAL_REJECT_SPIKE_THRESHOLD", "5"))
_APPROVAL_REJECT_WINDOW_SECONDS = int(os.getenv("ALERT_APPROVAL_REJECT_WINDOW_SECONDS", "300"))
_QUEUE_STUCK_SECONDS = int(os.getenv("ALERT_QUEUE_STUCK_SECONDS", "300"))


@dataclass
class AlertEvent:
    alert_id: str
    alert_type: str
    severity: str
    message: str
    correlation_id: Optional[str]
    symbol: Optional[str]
    metadata: Dict[str, Any]
    created_at: str


class AlertService:
    def __init__(self) -> None:
        self._events: Deque[AlertEvent] = deque(maxlen=_ALERTS_MAX_EVENTS)
        self._approval_reject_times: Deque[datetime.datetime] = deque()

    def _now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def emit(
        self,
        alert_type: str,
        message: str,
        *,
        severity: str = "warning",
        correlation_id: Optional[str] = None,
        symbol: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event = AlertEvent(
            alert_id=str(uuid4()),
            alert_type=alert_type,
            severity=severity,
            message=message,
            correlation_id=correlation_id,
            symbol=symbol,
            metadata=metadata or {},
            created_at=self._now().isoformat(),
        )
        self._events.append(event)
        payload = asdict(event)
        log_method = report_logger.error if severity in {"critical", "error"} else report_logger.warning
        log_method(f"operational_alert={payload}")
        return payload

    def record_approval_reject(
        self,
        *,
        correlation_id: Optional[str],
        symbol: Optional[str],
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        now = self._now()
        self._approval_reject_times.append(now)
        cutoff = now - datetime.timedelta(seconds=_APPROVAL_REJECT_WINDOW_SECONDS)
        while self._approval_reject_times and self._approval_reject_times[0] < cutoff:
            self._approval_reject_times.popleft()
        count = len(self._approval_reject_times)
        if count >= _APPROVAL_REJECT_SPIKE_THRESHOLD:
            return self.emit(
                "approval_reject_spike",
                f"Approval rejects reached {count} in {_APPROVAL_REJECT_WINDOW_SECONDS}s",
                severity="critical",
                correlation_id=correlation_id,
                symbol=symbol,
                metadata={"count": count, "window_seconds": _APPROVAL_REJECT_WINDOW_SECONDS, "reason": reason, **(metadata or {})},
            )
        return None

    def record_readiness_result(
        self,
        *,
        correlation_id: Optional[str],
        symbol: Optional[str],
        readiness: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        for key in ("technical", "fundamental"):
            report = readiness.get(key) or {}
            if report and not report.get("fresh", True):
                alerts.append(self.emit(
                    "readiness_validation_stale",
                    f"{key} validation report is stale or missing timestamp",
                    severity="critical",
                    correlation_id=correlation_id,
                    symbol=symbol,
                    metadata={"component": key, "report": report},
                ))
        if readiness.get("required") and not readiness.get("approved"):
            alerts.append(self.emit(
                "readiness_validation_rejected",
                readiness.get("reason") or "Readiness validation rejected execution",
                severity="critical",
                correlation_id=correlation_id,
                symbol=symbol,
                metadata={"readiness": readiness},
            ))
        return alerts

    def record_queue_status(
        self,
        *,
        queue_name: str,
        oldest_age_seconds: Optional[float],
        pending_count: Optional[int],
        correlation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if oldest_age_seconds is not None and oldest_age_seconds >= _QUEUE_STUCK_SECONDS:
            return self.emit(
                "queue_stuck",
                f"Queue {queue_name} has oldest pending job age {oldest_age_seconds}s",
                severity="critical",
                correlation_id=correlation_id,
                metadata={"queue_name": queue_name, "oldest_age_seconds": oldest_age_seconds, "pending_count": pending_count, **(metadata or {})},
            )
        return None

    def record_reconciliation_result(
        self,
        *,
        correlation_id: Optional[str],
        mismatch_count: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if mismatch_count > 0:
            return self.emit(
                "broker_database_mismatch",
                f"Broker/database reconciliation found {mismatch_count} mismatch(es)",
                severity="critical",
                correlation_id=correlation_id,
                metadata={"mismatch_count": mismatch_count, **(metadata or {})},
            )
        return None

    def list_events(self, limit: int = 100, alert_type: Optional[str] = None) -> List[Dict[str, Any]]:
        events = list(self._events)
        if alert_type:
            events = [event for event in events if event.alert_type == alert_type]
        return [asdict(event) for event in events[-limit:]]

    def summary(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for event in self._events:
            counts[event.alert_type] = counts.get(event.alert_type, 0) + 1
        return {"total": len(self._events), "counts": counts, "latest": self.list_events(limit=10)}


alert_service = AlertService()
