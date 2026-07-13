import unittest

from strategylab.strategies import CloseAboveThresholdStrategy, StrategyConfig


class StrategyConfigTest(unittest.TestCase):
    def test_strategy_builds_config_with_validated_defaults(self) -> None:
        strategy = CloseAboveThresholdStrategy()

        config = strategy.build_config({})

        self.assertEqual(config.strategy_name, "close_above_threshold")
        self.assertEqual(config.parameters["threshold"], 100.0)
        self.assertEqual(config.parameters["strength"], 1.0)

    def test_strategy_config_round_trip(self) -> None:
        original = StrategyConfig(
            strategy_name="close_above_threshold",
            strategy_version="0.1.0",
            parameters={"threshold": 111.0, "strength": 0.75},
        )

        restored = StrategyConfig.from_dict(original.to_dict())

        self.assertEqual(restored, original)


if __name__ == "__main__":
    unittest.main()

