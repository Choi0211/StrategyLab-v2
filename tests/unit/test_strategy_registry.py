import unittest

from strategylab.strategies import CloseAboveThresholdStrategy, StrategyRegistry


class StrategyRegistryTest(unittest.TestCase):
    def test_registry_registers_and_retrieves_strategy(self) -> None:
        registry = StrategyRegistry()

        registry.register(CloseAboveThresholdStrategy)

        self.assertEqual(registry.names(), ("close_above_threshold",))
        self.assertIs(registry.get("close_above_threshold"), CloseAboveThresholdStrategy)

    def test_registry_rejects_duplicate_strategy(self) -> None:
        registry = StrategyRegistry()
        registry.register(CloseAboveThresholdStrategy)

        with self.assertRaises(ValueError):
            registry.register(CloseAboveThresholdStrategy)

    def test_registry_rejects_unknown_strategy(self) -> None:
        registry = StrategyRegistry()

        with self.assertRaises(KeyError):
            registry.get("missing")


if __name__ == "__main__":
    unittest.main()

