"""Deterministic in-process event bus."""

from __future__ import annotations

from collections.abc import Callable

from gaon.runtime.events import EventType, RuntimeEvent

Subscriber = Callable[[RuntimeEvent], None]


class InMemoryEventBus:
    def __init__(self) -> None:
        self._events: tuple[RuntimeEvent, ...] = ()
        self._subscribers: tuple[Subscriber, ...] = ()

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers = (*self._subscribers, subscriber)

    def publish(self, event: RuntimeEvent) -> tuple[RuntimeEvent, ...]:
        if any(existing.event_id == event.event_id for existing in self._events):
            raise ValueError(f"duplicate event_id: {event.event_id}")
        emitted = [event]
        for subscriber in self._subscribers:
            try:
                subscriber(event)
            except Exception as exc:  # subscriber isolation is part of the contract
                emitted.append(
                    RuntimeEvent(
                        event_id=f"{event.event_id}:error:{len(emitted)}",
                        event_type=EventType.RUNTIME_ERROR_OCCURRED,
                        occurred_at=event.occurred_at,
                        actor="event-bus",
                        correlation_id=event.correlation_id,
                        causation_id=event.event_id,
                        scope=event.scope,
                        project=event.project,
                        strategy=event.strategy,
                        market=event.market,
                        payload={"error_type": exc.__class__.__name__},
                        evidence_refs=event.evidence_refs,
                        audit_ref=event.audit_ref,
                    )
                )
        self._events = (*self._events, *emitted)
        return tuple(emitted)

    def list_events(self) -> tuple[RuntimeEvent, ...]:
        return self._events
