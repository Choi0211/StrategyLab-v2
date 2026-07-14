from datetime import date, datetime
import unittest

from market_fixtures import sample_dataset, sample_provenance
from strategylab.market import MarketBar, MarketDataset


class MarketModelsTest(unittest.TestCase):
    def test_market_bar_constructs_ohlcv_data(self) -> None:
        bar = MarketBar("AAA", datetime(2026, 1, 1), 1.0, 2.0, 0.5, 1.5, 100.0)

        self.assertEqual(bar.symbol, "AAA")
        self.assertEqual(bar.close, 1.5)

    def test_market_bar_requires_symbol(self) -> None:
        with self.assertRaises(ValueError):
            MarketBar("", datetime(2026, 1, 1), 1.0, 2.0, 0.5, 1.5, 100.0)

    def test_dataset_reports_symbols_and_date_range(self) -> None:
        dataset = sample_dataset()

        self.assertEqual(dataset.symbols, ("AAA", "BBB"))
        self.assertEqual(dataset.start_date, date(2026, 1, 1))
        self.assertEqual(dataset.end_date, date(2026, 1, 3))

    def test_dataset_filter_preserves_provenance(self) -> None:
        dataset = sample_dataset()

        filtered = dataset.filter(symbol="AAA", start=date(2026, 1, 2), end=date(2026, 1, 2))

        self.assertEqual(len(filtered.bars), 1)
        self.assertEqual(filtered.bars[0].symbol, "AAA")
        self.assertIs(filtered.provenance, dataset.provenance)

    def test_provenance_records_required_audit_fields(self) -> None:
        provenance = sample_provenance()

        self.assertEqual(provenance.source.source_name, "synthetic-fixture")
        self.assertEqual(provenance.source.frequency, "1d")
        self.assertEqual(provenance.source.timezone, "Asia/Seoul")
        self.assertEqual(provenance.symbol_universe, ("AAA", "BBB"))
        self.assertEqual(provenance.preprocessing_steps, ("synthetic fixture",))

    def test_empty_dataset_has_no_date_range(self) -> None:
        dataset = MarketDataset(bars=(), provenance=sample_provenance())

        self.assertIsNone(dataset.start_date)
        self.assertIsNone(dataset.end_date)


if __name__ == "__main__":
    unittest.main()

