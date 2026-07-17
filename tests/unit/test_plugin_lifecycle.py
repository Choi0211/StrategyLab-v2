import unittest

from gaon.runtime.errors import ConfigurationError
from gaon.runtime.plugins import (
    FakeNotionPlugin,
    FakeTelegramPlugin,
    FakeTradingPlugin,
    PluginCapabilities,
    PluginManager,
    PluginMetadata,
    PluginRegistry,
)


class PluginLifecycleTest(unittest.TestCase):
    def test_registration_duplicate_and_security_rejection(self) -> None:
        registry = PluginRegistry()
        registry.register(FakeTelegramPlugin())

        with self.assertRaises(ConfigurationError):
            registry.register(FakeTelegramPlugin())

        class BadPlugin(FakeTelegramPlugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata("bad", "Bad", "1.0", True, PluginCapabilities(migrations=True))

        with self.assertRaises(ConfigurationError):
            registry.register(BadPlugin())

    def test_deterministic_start_and_reverse_stop_order(self) -> None:
        log: list[str] = []
        registry = PluginRegistry()
        registry.register(FakeTradingPlugin(log=log))
        registry.register(FakeTelegramPlugin(log=log))
        registry.register(FakeNotionPlugin(log=log))
        manager = PluginManager(registry)

        manager.configure()
        manager.start()
        manager.stop()

        self.assertEqual([entry for entry in log if entry.startswith("start:")], ["start:notion", "start:telegram", "start:trading"])
        self.assertEqual([entry for entry in log if entry.startswith("stop:")], ["stop:trading", "stop:telegram", "stop:notion"])

    def test_disabled_plugin_does_not_start(self) -> None:
        log: list[str] = []
        registry = PluginRegistry()
        registry.register(FakeTelegramPlugin(enabled=False, log=log))
        manager = PluginManager(registry)

        manager.start()

        self.assertEqual(log, [])
        self.assertEqual(manager.failures[0]["status"], "disabled")

    def test_start_failure_isolation_and_redaction(self) -> None:
        log: list[str] = []
        registry = PluginRegistry()
        registry.register(FakeTelegramPlugin("a-telegram", fail_start=True, log=log))
        registry.register(FakeNotionPlugin("b-notion", log=log))
        manager = PluginManager(registry)

        manager.start()

        self.assertIn("start:b-notion", log)
        self.assertEqual(manager.failures[0]["status"], "start_failed")
        self.assertNotIn("secret-token", str(manager.failures))

    def test_health_aggregation_and_fake_trading_no_network(self) -> None:
        registry = PluginRegistry()
        registry.register(FakeTradingPlugin())
        manager = PluginManager(registry)
        manager.start()

        health = manager.health()
        trading = registry.get("trading")

        self.assertTrue(health[0].healthy)
        self.assertFalse(trading.metadata.capabilities.network)


if __name__ == "__main__":
    unittest.main()
