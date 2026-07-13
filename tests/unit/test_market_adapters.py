from datetime import date
import unittest

from market_fixtures import sample_dataset
from strategylab.market import InMemoryMarketDataAdapter


class MarketAdaptersTest(unittest.TestCase):
    def test_in_memory_adapter_loads_requested_symbols(self) -> None:
        adapter = InMemoryMarketDataAdapter(sample_dataset())

        dataset = adapter.load(symbols=("AAA",))

        self.assertEqual(dataset.symbols, ("AAA",))
        self.assertEqual(len(dataset.bars), 2)

    def test_in_memory_adapter_filters_date_range(self) -> None:
        adapter = InMemoryMarketDataAdapter(sample_dataset())

        dataset = adapter.load(symbols=("AAA", "BBB"), start=date(2026, 1, 2), end=date(2026, 1, 3))

        self.assertEqual(len(dataset.bars), 2)
        self.assertEqual(dataset.start_date, date(2026, 1, 2))
        self.assertEqual(dataset.end_date, date(2026, 1, 3))

    def test_in_memory_adapter_returns_empty_dataset_for_unknown_symbol(self) -> None:
        adapter = InMemoryMarketDataAdapter(sample_dataset())

        dataset = adapter.load(symbols=("ZZZ",))

        self.assertEqual(dataset.bars, ())
        self.assertEqual(dataset.symbols, ())


if __name__ == "__main__":
    unittest.main()

