import unittest

from strategylab.core import ModuleDefinition, ModuleRegistry, default_module_registry


class ModuleRegistryTest(unittest.TestCase):
    def test_default_module_registry_matches_blueprint(self) -> None:
        registry = default_module_registry()

        self.assertEqual(
            registry.names(),
            (
                "core",
                "market",
                "strategies",
                "portfolio",
                "risk",
                "backtest",
                "research",
                "broker",
                "dashboard",
                "reports",
                "notification",
            ),
        )
        self.assertEqual(registry.get("backtest").package, "strategylab.backtest")


    def test_registry_rejects_duplicate_modules(self) -> None:
        module = ModuleDefinition("core", "strategylab.core", "core")
        registry = ModuleRegistry([module])

        with self.assertRaises(ValueError):
            registry.register(module)


if __name__ == "__main__":
    unittest.main()
