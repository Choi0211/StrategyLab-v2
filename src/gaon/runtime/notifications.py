"""Deterministic notification engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from gaon.runtime.events import EventType, RuntimeEvent


class NotificationChannel(str, Enum):
    TELEGRAM = "telegram"
    NOTION = "notion"
    INTERNAL = "internal"
    MULTI_CHANNEL = "multi_channel"


class NotificationPriority(str, Enum):
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class NotificationRequest:
    request_id: str
    channel: NotificationChannel
    priority: NotificationPriority
    title: str
    body: str
    deduplication_key: str
    correlation_id: str


@dataclass(frozen=True)
class NotificationResult:
    request_id: str
    channel: NotificationChannel
    delivered: bool
    dry_run: bool
    error: str | None = None


class NotificationEngine:
    def __init__(self) -> None:
        self._dedupe: set[str] = set()

    def from_event(self, event: RuntimeEvent) -> NotificationRequest | None:
        priority = _EVENT_PRIORITY.get(event.event_type)
        if priority is None:
            return None
        return NotificationRequest(
            request_id=f"notification:{event.event_id}",
            channel=NotificationChannel.MULTI_CHANNEL,
            priority=priority,
            title=event.event_type.value,
            body=str(event.payload.get("summary", event.event_type.value)),
            deduplication_key=f"{event.event_type.value}:{event.correlation_id}:{event.occurred_at[:10]}",
            correlation_id=event.correlation_id,
        )

    def dispatch(self, request: NotificationRequest, *, dry_run: bool = True) -> NotificationResult:
        if request.deduplication_key in self._dedupe:
            return NotificationResult(request.request_id, request.channel, delivered=False, dry_run=dry_run, error="duplicate")
        self._dedupe.add(request.deduplication_key)
        return NotificationResult(request.request_id, request.channel, delivered=True, dry_run=dry_run)


_EVENT_PRIORITY = {
    EventType.RESEARCH_COMPLETED: NotificationPriority.NOTICE,
    EventType.RESEARCH_FAILED: NotificationPriority.WARNING,
    EventType.CONFLICT_CANDIDATE_DETECTED: NotificationPriority.CRITICAL,
    EventType.REVALIDATION_DUE: NotificationPriority.WARNING,
    EventType.POLICY_APPROVAL_REQUIRED: NotificationPriority.NOTICE,
    EventType.PREFERENCE_APPROVAL_REQUIRED: NotificationPriority.NOTICE,
    EventType.DAILY_REPORT_GENERATED: NotificationPriority.INFO,
    EventType.WEEKLY_REVIEW_GENERATED: NotificationPriority.INFO,
}
