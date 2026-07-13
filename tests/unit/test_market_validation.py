from dataclasses import replace
from datetime import date, datetime
import unittest

from market_fixtures import sample_dataset, sample_provenance
from strategylab.market import MarketBar, MarketDataset, MarketDataValidator


class MarketValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = MarketDataValidator()

    def test_valid_dataset_passes(self) -> None:
        result = self.validator.validate(sample_dataset(), expected_symbols=("AAA", "BBB"))

        self.assertTrue(result.passed)
        self.assertEqual(result.issues, ())

    def test_empty_dataset_fails(self) -> None:
        result = self.validator.validate(MarketDataset(bars=(), provenance=sample_provenance()))

        self.assertFalse(result.passed)
        self.assertIn("empty_dataset", {issue.code for issue in result.issues})

    def test_missing_value_fails(self) -> None:
        dataset = MarketDataset(
            bars=(
                MarketBar("AAA", datetime(2026, 1, 1), 100.0, 110.0, 95.0, None, 1000.0),  # type: ignore[arg-type]
            ),
            provenance=sample_provenance(),
        )

        result = self.validator.validate(dataset)

        self.assertFalse(result.passed)
        self.assertIn("missing_value", {issue.code for issue in result.issues})

    def test_duplicate_timestamp_fails(self) -> None:
        dataset = sample_dataset()
        duplicate = dataset.bars[0]
        with_duplicate = MarketDataset(bars=dataset.bars + (duplicate,), provenance=dataset.provenance)

        result = self.validator.validate(with_duplicate)

        self.assertFalse(result.passed)
        self.assertIn("duplicate_timestamp", {issue.code for issue in result.issues})

    def test_symbol_universe_mismatch_fails(self) -> None:
        result = self.validator.validate(sample_dataset(), expected_symbols=("AAA", "CCC"))

        self.assertFalse(result.passed)
        self.assertIn("symbol_universe_mismatch", {issue.code for issue in result.issues})

    def test_date_range_before_requested_start_fails(self) -> None:
        result = self.validator.validate(sample_dataset(), start=date(2026, 1, 2))

        self.assertFalse(result.passed)
        self.assertIn("date_range_mismatch", {issue.code for issue in result.issues})

    def test_date_range_after_requested_end_fails(self) -> None:
        result = self.validator.validate(sample_dataset(), end=date(2026, 1, 2))

        self.assertFalse(result.passed)
        self.assertIn("date_range_mismatch", {issue.code for issue in result.issues})

    def test_invalid_ohlc_fails(self) -> None:
        dataset = sample_dataset()
        bad_bar = replace(dataset.bars[0], high=90.0, low=95.0)

        result = self.validator.validate(MarketDataset(bars=(bad_bar,), provenance=dataset.provenance))

        self.assertFalse(result.passed)
        self.assertIn("invalid_ohlc", {issue.code for issue in result.issues})

    def test_negative_volume_fails(self) -> None:
        dataset = sample_dataset()
        bad_bar = replace(dataset.bars[0], volume=-1.0)

        result = self.validator.validate(MarketDataset(bars=(bad_bar,), provenance=dataset.provenance))

        self.assertFalse(result.passed)
        self.assertIn("invalid_volume", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()

