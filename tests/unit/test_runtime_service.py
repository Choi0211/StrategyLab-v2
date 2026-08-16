import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from gaon.runtime.cli import main as cli_main, _runtime_tick
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.health import readiness
from gaon.runtime.migrations import SCHEMA_VERSION
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.scheduled_automation import ScheduledJobRepository
from gaon.runtime.service import GaonRuntimeService
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_worker import TelegramPollingWorker
from gaon.runtime.worker import DuplicateMessageGuard, RetryPolicy


class RuntimeServiceTest(unittest.TestCase):
    def test_sqlite_migration_offset_duplicate_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            backup = os.path.join(tmp, "backup.sqlite")
            store = RuntimeStateStore(db)
            self.assertTrue(store.status().ready)
            store.save_offset("100", 42, "2026-07-17T00:00:00Z")
            self.assertEqual(store.get_offset("100"), 42)
            self.assertTrue(store.mark_processed("msg-1", "2026-07-17T00:00:00Z"))
            self.assertFalse(store.mark_processed("msg-1", "2026-07-17T00:00:00Z"))
            store.append_audit("event-1", "test", "{}", "2026-07-17T00:00:00Z")
            self.assertEqual(store.list_audit(), ("event-1",))
            self.assertEqual(store.backup(backup), backup)
            store.close()
            self.assertTrue(os.path.exists(backup))

    def test_health_service_retry_and_duplicate_guard(self) -> None:
        store = RuntimeStateStore(":memory:")
        ticks: list[str] = []
        service = GaonRuntimeService(GaonRuntimeConfig(), store)
        self.assertTrue(all(check.ready for check in readiness(GaonRuntimeConfig(), store)))
        self.assertTrue(service.start().running)
        service = GaonRuntimeService(GaonRuntimeConfig(telegram_bot_token="synthetic-token"), store, tick=lambda: ticks.append("tick"), poll_interval_seconds=0.0)
        self.assertEqual(service.run_once().ticks, 1)
        self.assertEqual(ticks, ["tick"])
        self.assertNotIn("synthetic-token", str(service.logs))
        self.assertFalse(service.stop().running)
        self.assertEqual(RetryPolicy(max_attempts=3, base_delay_seconds=1, max_delay_seconds=3).delay_for_attempt(3), 3)
        guard = DuplicateMessageGuard()
        self.assertTrue(guard.mark("m1"))
        self.assertFalse(guard.mark("m1"))
        store.close()

    def test_cli_health_and_db_check(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["health"]), 0)
        self.assertIn("database: ready", output.getvalue())
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["db-check"]), 0)
        self.assertIn(f"schema_version={SCHEMA_VERSION}", output.getvalue())
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["run", "--once"]), 0)
        self.assertIn("ticks=1", output.getvalue())
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["status"]), 0)
        self.assertIn("running=False", output.getvalue())

    def test_deployment_import_path_check_requires_project_source(self) -> None:
        expected = os.path.abspath(os.path.join(os.getcwd(), "src", "gaon"))
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["deployment-import-path-check", "--expected-source", expected]), 0)
        self.assertIn("deployment-import-path-check: PASS", output.getvalue())
        self.assertIn(expected, output.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cli_main(["deployment-import-path-check", "--expected-source", os.path.join(tmp, "src", "gaon")]), 1)
            self.assertIn("unexpected gaon import path", stderr.getvalue())

    def test_telegram_runtime_tick_polls_and_reuses_persisted_offset(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = _FakeTelegramClient(({"update_id": 10, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 1}, "text": "/status"}},))
        try:
            worker = TelegramPollingWorker(_execute_telegram_config(), store, client_factory=lambda _: client, poll_timeout_seconds=3, batch_limit=7)

            first = worker.tick()
            second = worker.tick()

            self.assertTrue(first.attempted)
            self.assertEqual(first.results[0].status, "sent")
            self.assertEqual(second.results[0].status, "duplicate")
            self.assertEqual(client.calls, [(None, 3, 7), (11, 3, 7)])
            self.assertEqual(len(client.sent), 1)
        finally:
            store.close()

    def test_telegram_worker_skips_disabled_and_dry_run_without_network(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            disabled = TelegramPollingWorker(GaonRuntimeConfig(), store, client_factory=lambda _: _FailingTelegramClient())
            dry_run = TelegramPollingWorker(GaonRuntimeConfig(telegram_enabled=True, telegram_bot_token="synthetic-token"), store, client_factory=lambda _: _FailingTelegramClient())

            self.assertFalse(disabled.tick().attempted)
            self.assertFalse(dry_run.tick().attempted)
        finally:
            store.close()

    def test_telegram_transient_failure_does_not_terminate_runtime(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = _FlakyTelegramClient(({"update_id": 20, "message": {"message_id": 2, "chat": {"id": 100}, "from": {"id": 1}, "text": "/status"}},))
        try:
            worker = TelegramPollingWorker(_execute_telegram_config(), store, client_factory=lambda _: client)
            service = GaonRuntimeService(_execute_telegram_config(), store, tick=worker.tick, poll_interval_seconds=0.0)

            failed = service.run_once()
            recovered = service.run_once()

            self.assertEqual(failed.ticks, 1)
            self.assertEqual(recovered.ticks, 2)
            self.assertEqual(len(client.sent), 1)
            self.assertEqual(store.telegram.get_offset("__telegram_poll__"), 21)
        finally:
            store.close()

    def test_runtime_tick_invokes_telegram_and_daily_briefing_scheduler(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = _FakeTelegramClient(({"update_id": 40, "message": {"message_id": 4, "chat": {"id": 100}, "from": {"id": 1}, "text": "/status"}},))
        try:
            tick = _runtime_tick(
                _execute_telegram_config(),
                store,
                MetricsCollector(),
                telegram_client_factory=lambda _: client,
                briefing_client_factory=lambda _: client,
                briefing_now_factory=lambda: "2026-08-17T00:00:00Z",
            )

            first = tick()
            second = tick()

            self.assertTrue(first["telegram"].attempted)
            self.assertTrue(first["daily_briefing"].attempted)
            self.assertTrue(first["daily_briefing"].jobs_registered)
            self.assertFalse(second["daily_briefing"].jobs_registered)
            self.assertEqual(len([job for job in ScheduledJobRepository(store._connection).list() if (job.metadata or {}).get("kind") == "daily_briefing"]), 3)
            self.assertEqual(len(client.sent), 1)
        finally:
            store.close()

    def test_daily_briefing_runtime_release_check_cli_passes(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["gaon-production-daily-briefing-runtime-wiring-release-check"]), 0)
        self.assertIn("telegram_worker_invoked=true", output.getvalue())
        self.assertIn("daily_briefing_worker_invoked=true", output.getvalue())
        self.assertIn("safety=pass", output.getvalue())


class _FakeTelegramClient:
    def __init__(self, updates: tuple[dict, ...]) -> None:
        self.updates = updates
        self.sent: list[tuple[str, str]] = []
        self.calls: list[tuple[int | None, int, int]] = []

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        self.calls.append((offset, timeout, limit))
        return self.updates

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


class _FailingTelegramClient:
    def get_updates(self, *, offset=None, timeout=0, limit=100):
        raise AssertionError("network should not be called")


class _FlakyTelegramClient(_FakeTelegramClient):
    def __init__(self, updates: tuple[dict, ...]) -> None:
        super().__init__(updates)
        self.fail_next = True

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("temporary telegram failure")
        return super().get_updates(offset=offset, timeout=timeout, limit=limit)


def _execute_telegram_config() -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        mode="execute",
        dry_run=False,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_allowed_chat_ids=("100",),
        approval_signing_secret="synthetic-approval-secret",
    )


if __name__ == "__main__":
    unittest.main()
