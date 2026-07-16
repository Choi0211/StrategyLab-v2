"""Runtime audit helpers."""

from __future__ import annotations

from gaon.runtime.events import RuntimeEvent


def audit_ref_for_event(event: RuntimeEvent) -> str:
    return f"audit:{event.event_id}"
