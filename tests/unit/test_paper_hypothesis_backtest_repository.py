"""Unit tests for gaon.runtime.paper_hypothesis_backtest_repository."""

from __future__ import annotations

import unittest

from gaon.runtime.paper_hypothesis_backtest_repository import PaperHypothesisBacktestSQLiteRepository
from gaon.runtime.storage import RuntimeStateStore

FAMILY_ID = "csm-48h-long"


def _result(**overrides: object) -> dict:
    base = {
        "family_id": FAMILY_ID,
        "hypothesis_id": "hypothesis:csm-48h-long:symbol_concentration:abc123",
        "hypothesis_fingerprint": "sha256:abc123",
        "backtest_fingerprint": "sha256:backtest-abc123",
        "verdict": "pass",
        "metrics": {"oos_pf": 1.6, "oos_n": 120, "mdd_pct": -8.2},
        "data_source": "local_1m_kline_cache",
        "data_period_start": "2026-03-01T00:00:00Z",
        "data_period_end": "2026-09-28T23:59:00Z",
        "symbols_processed": 23,
        "fee_assumption_pct": 0.30,
        "slippage_note": "bundled into round-trip fee assumption, not modeled separately",
        "oos_validated": True,
        "tested_at": "2026-10-20T00:00:00Z",
    }
    base.update(overrides)
    return base


class PaperHypothesisBacktestRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.repo = PaperHypothesisBacktestSQLiteRepository(self.store._connection)

    def test_insert_requires_all_required_fields(self) -> None:
        incomplete = _result()
        del incomplete["metrics"]
        with self.assertRaises(KeyError):
            self.repo.insert(incomplete, created_at="t1")

    def test_insert_rejects_unrecognized_verdict(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.insert(_result(verdict="definitely_promote_it"), created_at="t1")

    def test_insert_and_list_round_trips_structured_fields(self) -> None:
        bt_id = self.repo.insert(_result(), created_at="t1")
        self.assertIsInstance(bt_id, int)
        rows = self.repo.list_for_family(FAMILY_ID)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "pass")
        self.assertEqual(rows[0]["metrics"], {"oos_pf": 1.6, "oos_n": 120, "mdd_pct": -8.2})
        self.assertTrue(rows[0]["oos_validated"])
        self.assertEqual(rows[0]["symbols_processed"], 23)

    def test_resending_identical_fingerprint_is_idempotent(self) -> None:
        first = self.repo.insert(_result(), created_at="t1")
        second = self.repo.insert(_result(), created_at="t2")
        self.assertEqual(first, second)
        self.assertEqual(len(self.repo.list_for_family(FAMILY_ID)), 1)

    def test_list_passed_excludes_other_verdicts(self) -> None:
        self.repo.insert(_result(backtest_fingerprint="sha256:a", verdict="pass"), created_at="t1")
        self.repo.insert(_result(backtest_fingerprint="sha256:b", verdict="fail"), created_at="t2")
        self.repo.insert(_result(backtest_fingerprint="sha256:c", verdict="needs_revalidation"), created_at="t3")
        self.repo.insert(_result(backtest_fingerprint="sha256:d", verdict="insufficient_data"), created_at="t4")
        passed = self.repo.list_passed_for_family(FAMILY_ID)
        self.assertEqual(len(passed), 1)
        self.assertEqual(passed[0]["backtest_fingerprint"], "sha256:a")

    def test_list_for_hypothesis_filters_by_hypothesis_fingerprint(self) -> None:
        self.repo.insert(_result(hypothesis_fingerprint="sha256:h1", backtest_fingerprint="sha256:a"), created_at="t1")
        self.repo.insert(_result(hypothesis_fingerprint="sha256:h2", backtest_fingerprint="sha256:b"), created_at="t2")
        rows = self.repo.list_for_hypothesis(FAMILY_ID, "sha256:h1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hypothesis_fingerprint"], "sha256:h1")

    def test_oos_not_validated_is_stored_as_false(self) -> None:
        self.repo.insert(_result(oos_validated=False, verdict="needs_revalidation"), created_at="t1")
        rows = self.repo.list_for_family(FAMILY_ID)
        self.assertFalse(rows[0]["oos_validated"])


if __name__ == "__main__":
    unittest.main()
