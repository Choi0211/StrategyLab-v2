import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.plugins import FakeNotionPlugin, FakeTelegramPlugin, PluginManager, PluginRegistry
from gaon.runtime.service import GaonRuntimeService
from gaon.runtime.storage import RuntimeStateStore


class PhaseARuntimeIntegrationTest(unittest.TestCase):
    def test_service_starts_plugins_and_records_metrics(self) -> None:
        log: list[str] = []
        registry = PluginRegistry()
        registry.register(FakeTelegramPlugin(log=log))
        registry.register(FakeNotionPlugin(log=log))
        manager = PluginManager(registry)
        metrics = MetricsCollector()
        store = RuntimeStateStore(":memory:")

        service = GaonRuntimeService(GaonRuntimeConfig(), store, metrics=metrics, plugin_manager=manager)
        service.run_once()
        service.stop()

        text = metrics.snapshot().to_text()
        self.assertIn("plugin_health", text)
        self.assertIn("runtime_loops", text)
        self.assertEqual([entry for entry in log if entry.startswith("start:")], ["start:notion", "start:telegram"])
        self.assertEqual([entry for entry in log if entry.startswith("stop:")], ["stop:telegram", "stop:notion"])
        store.close()

    def test_cli_event_replay_dry_run(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["event-replay-dry-run"]), 0)
        self.assertIn("event-replay-dry-run", output.getvalue())


if __name__ == "__main__":
    unittest.main()
