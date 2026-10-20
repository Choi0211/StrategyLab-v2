"""Unit tests for gaon.runtime.paper_failure_hypothesis_repository."""

from __future__ import annotations

import unittest

from gaon.runtime.paper_failure_hypothesis_repository import PaperFailureHypothesisSQLiteRepository
from gaon.runtime.storage import RuntimeStateStore

FAMILY_ID = "csm-48h-long"


def _hypothesis(**overrides: object) -> dict:
    base = {
        "family_id": FAMILY_ID,
        "hypothesis_id": "hypothesis:csm-48h-long:symbol_concentration:abc123",
        "fingerprint": "sha256:abc123",
        "pattern_type": "symbol_concentration",
        "status": "candidate",
        "statement": "QNTUSDT accounts for 45% of net PnL",
        "trade_count": 12,
        "confidence": 0.4,
        "evidence": {"top_symbol": "QNTUSDT", "top_symbol_share": 0.45},
        "expected_improvement": "Consider capping per-symbol exposure",
        "verification_required": ["historical backtest", "paper forward re-run"],
        "generated_at": "2026-10-22T00:00:00Z",
    }
    base.update(overrides)
    return base


class PaperFailureHypothesisRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.repo = PaperFailureHypothesisSQLiteRepository(self.store._connection)

    def test_insert_requires_all_required_fields(self) -> None:
        incomplete = _hypothesis()
        del incomplete["statement"]
        with self.assertRaises(KeyError):
            self.repo.insert(incomplete, created_at="t1")

    def test_insert_and_list_round_trips_structured_fields(self) -> None:
        hyp_id = self.repo.insert(_hypothesis(), created_at="t1")
        self.assertIsInstance(hyp_id, int)
        rows = self.repo.list_for_family(FAMILY_ID)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pattern_type"], "symbol_concentration")
        self.assertEqual(rows[0]["status"], "candidate")
        self.assertAlmostEqual(rows[0]["confidence"], 0.4)
        self.assertEqual(rows[0]["evidence"], {"top_symbol": "QNTUSDT", "top_symbol_share": 0.45})
        self.assertEqual(rows[0]["verification_required"], ["historical backtest", "paper forward re-run"])

    def test_insufficient_evidence_hypothesis_has_null_confidence(self) -> None:
        self.repo.insert(_hypothesis(status="insufficient_evidence", confidence=None), created_at="t1")
        rows = self.repo.list_for_family(FAMILY_ID)
        self.assertIsNone(rows[0]["confidence"])

    def test_resending_identical_fingerprint_is_idempotent_not_duplicated(self) -> None:
        first_id = self.repo.insert(_hypothesis(), created_at="t1")
        second_id = self.repo.insert(_hypothesis(), created_at="t2")  # same fingerprint
        self.assertEqual(first_id, second_id)
        self.assertEqual(len(self.repo.list_for_family(FAMILY_ID)), 1)

    def test_different_fingerprint_for_same_family_is_a_new_row(self) -> None:
        self.repo.insert(_hypothesis(fingerprint="sha256:aaa"), created_at="t1")
        self.repo.insert(_hypothesis(fingerprint="sha256:bbb"), created_at="t2")
        self.assertEqual(len(self.repo.list_for_family(FAMILY_ID)), 2)

    def test_list_candidates_excludes_insufficient_evidence(self) -> None:
        self.repo.insert(_hypothesis(fingerprint="sha256:aaa", status="candidate"), created_at="t1")
        self.repo.insert(
            _hypothesis(fingerprint="sha256:bbb", status="insufficient_evidence", confidence=None),
            created_at="t2",
        )
        candidates = self.repo.list_candidates_for_family(FAMILY_ID)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["status"], "candidate")

    def test_list_is_isolated_per_family(self) -> None:
        self.repo.insert(_hypothesis(), created_at="t1")
        self.repo.insert(_hypothesis(family_id="other-family", fingerprint="sha256:other"), created_at="t2")
        self.assertEqual(len(self.repo.list_for_family(FAMILY_ID)), 1)
        self.assertEqual(len(self.repo.list_for_family("other-family")), 1)


if __name__ == "__main__":
    unittest.main()
