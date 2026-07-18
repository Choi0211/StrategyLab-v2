import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.health import readiness
from gaon.runtime.service import GaonRuntimeService
from gaon.runtime.storage import RuntimeStateStore
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
        self.assertIn("schema_version=9", output.getvalue())
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["run"]), 0)
        self.assertIn("ticks=1", output.getvalue())
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["status"]), 0)
        self.assertIn("running=False", output.getvalue())


if __name__ == "__main__":
    unittest.main()
