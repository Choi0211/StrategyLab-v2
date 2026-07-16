"""Audit helpers for Learning Memory runtime."""

from __future__ import annotations

from gaon.learning.contracts import AuditAction, AuditEvent
from gaon.learning.time import parse_iso8601_utc


def sort_audit_events(events: tuple[AuditEvent, ...]) -> tuple[AuditEvent, ...]:
    """Return audit events in deterministic chronological order."""

    return tuple(sorted(events, key=lambda event: (parse_iso8601_utc(event.timestamp, "timestamp"), event.event_id)))


def filter_audit_events(
    events: tuple[AuditEvent, ...],
    *,
    target_ref: str | None = None,
    action: AuditAction | None = None,
) -> tuple[AuditEvent, ...]:
    """Filter audit events by target and action using AND semantics."""

    filtered = sort_audit_events(events)
    if target_ref is not None:
        filtered = tuple(event for event in filtered if event.target_ref == target_ref)
    if action is not None:
        filtered = tuple(event for event in filtered if event.action is action)
    return filtered
