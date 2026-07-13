import unittest

from market_fixtures import sample_dataset
from strategylab.strategies import CloseAboveThresholdStrategy, SignalType


class StrategySignalsTest(unittest.TestCase):
    def test_example_strategy_produces_deterministic_signals(self) -> None:
        strategy = CloseAboveThresholdStrategy()
        config = strategy.build_config({"threshold": 100.0, "strength": 0.8})
        dataset = sample_dataset()

        first = strategy.generate_signals(dataset, config)
        second = strategy.generate_signals(dataset, config)

        self.assertEqual(first, second)
        self.assertEqual(len(first), len(dataset.bars))

    def test_signal_contract_fields(self) -> None:
        strategy = CloseAboveThresholdStrategy()
        config = strategy.build_config({"threshold": 100.0})
        signal = strategy.generate_signals(sample_dataset(), config)[0]

        self.assertEqual(signal.symbol, "AAA")
        self.assertEqual(signal.signal_type, SignalType.BUY)
        self.assertEqual(signal.strength, 1.0)
        self.assertIn("threshold", signal.reason)
        self.assertEqual(signal.strategy_name, "close_above_threshold")

    def test_example_strategy_emits_hold_below_threshold(self) -> None:
        strategy = CloseAboveThresholdStrategy()
        config = strategy.build_config({"threshold": 999.0})

        signals = strategy.generate_signals(sample_dataset(), config)

        self.assertTrue(all(signal.signal_type is SignalType.HOLD for signal in signals))
        self.assertTrue(all(signal.strength == 0.0 for signal in signals))

    def test_invalid_signal_strength_is_rejected_before_generation(self) -> None:
        strategy = CloseAboveThresholdStrategy()

        with self.assertRaises(ValueError):
            strategy.build_config({"strength": 1.1})


if __name__ == "__main__":
    unittest.main()

