"""Bounded Telegram polling worker for GaonRuntimeService."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Protocol
from uuid import uuid4

from gaon.integrations.telegram.contracts import TelegramPollResult
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import GaonRuntimeError
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.storage import RuntimeStateStore


class TelegramPollingClient(Protocol):
    def get_updates(self, *, offset: int | None = None, timeout: int = 0, limit: int = 100) -> tuple[dict, ...]: ...
    def send_message(self, chat_id: str, text: str, parse_mode: str | None = None, reply_to_message_id: str | None = None): ...


@dataclass(frozen=True)
class TelegramPollingTickResult:
    enabled: bool
    attempted: bool
    results: tuple[TelegramPollResult, ...] = ()
    error_type: str | None = None


class TelegramPollingWorker:
    """Runs one bounded Telegram poll and isolates transient failures."""

    def __init__(
        self,
        config: GaonRuntimeConfig,
        store: RuntimeStateStore,
        *,
        client_factory: Callable[[GaonRuntimeConfig], TelegramPollingClient],
        metrics: MetricsCollector | None = None,
        poll_timeout_seconds: int = 5,
        batch_limit: int = 50,
    ) -> None:
        if poll_timeout_seconds < 0 or poll_timeout_seconds > 30:
            raise ValueError("telegram poll timeout must be between 0 and 30 seconds")
        if batch_limit < 1 or batch_limit > 100:
            raise ValueError("telegram batch limit must be between 1 and 100")
        self._config = config
        self._store = store
        self._client_factory = client_factory
        self._metrics = metrics or MetricsCollector()
        self._poll_timeout_seconds = poll_timeout_seconds
        self._batch_limit = batch_limit

    def tick(self) -> TelegramPollingTickResult:
        now = _utc_now()
        if not self._should_poll():
            self._metrics.increment("telegram_poll_skipped", reason="disabled")
            return TelegramPollingTickResult(enabled=False, attempted=False)
        try:
            client = self._client_factory(self._config)
            from gaon.runtime.cli import poll_once

            results = poll_once(
                client,
                self._config,
                offset=None,
                received_at=now,
                state=self._store.telegram,
                timeout=self._poll_timeout_seconds,
                limit=self._batch_limit,
            )
        except GaonRuntimeError as exc:
            return self._record_failure(exc, now)
        except Exception as exc:  # noqa: BLE001 - runtime must survive transient transport failures.
            return self._record_failure(exc, now)
        self._metrics.increment("telegram_poll_ticks", status="ok")
        self._metrics.increment("telegram_poll_updates", amount=len(results), status="observed")
        self._append_event("TelegramPollingTickCompleted", now, {"updates": len(results), "statuses": _status_counts(results)})
        return TelegramPollingTickResult(enabled=True, attempted=True, results=results)

    def _should_poll(self) -> bool:
        return self._config.mode == "execute" and not self._config.dry_run and self._config.telegram_enabled

    def _record_failure(self, exc: Exception, now: str) -> TelegramPollingTickResult:
        error_type = exc.__class__.__name__
        self._metrics.increment("telegram_poll_ticks", status="failed")
        self._append_event("TelegramPollingTickFailed", now, {"error_type": error_type})
        return TelegramPollingTickResult(enabled=True, attempted=True, error_type=error_type)

    def _append_event(self, event_type: str, now: str, payload: dict[str, object]) -> None:
        SQLiteEventStore(self._store._connection).append(
            DurableEvent(
                event_id=f"telegram-poll:{uuid4().hex}",
                event_type=event_type,
                occurred_at=now,
                actor_ref="runtime:telegram-worker",
                correlation_id="telegram-poll",
                causation_id=None,
                scope="runtime",
                project="StrategyLab",
                strategy="N/A",
                market="N/A",
                payload=payload,
                evidence_refs=(),
                audit_refs=(),
                appended_at=now,
            )
        )


def _status_counts(results: tuple[TelegramPollResult, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
