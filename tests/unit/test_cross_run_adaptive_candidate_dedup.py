from __future__ import annotations

import sqlite3
import unittest

from gaon.knowledge.autonomous_quant_partner import (
    _persistent_adaptive_fingerprints,
    _remember_adaptive_candidate,
    _select_unique_adaptive_candidate,
    _strategy_semantic_fingerprint,
)
from gaon.research.krx_real_pipeline import (
    CanonicalStrategySpec,
    FieldProvenance,
    ProvenancedValue,
)


def _v(value, provenance=FieldProvenance.DEFAULT):
    return ProvenancedValue(value, provenance)


def _strategy(spec_id: str, created_at: str) -> CanonicalStrategySpec:
    return CanonicalStrategySpec(
        spec_id,
        "005930",
        {
            "breakout_lookback": _v(30),
            "close_gt_ma20": _v(True),
        },
        {"protective_stop_pct": _v(-5.0)},
        {"volume_gte_ma20": _v(True)},
        "same behavior, different run metadata",
        created_at,
    )


class CrossRunAdaptiveCandidateDedupTests(unittest.TestCase):
    def test_semantic_fingerprint_ignores_run_metadata_and_provenance(self) -> None:
        a = _strategy("run:a", "2026-08-15T01:00:00Z")
        b = _strategy("run:b", "2026-08-15T02:00:00Z")
        b = CanonicalStrategySpec(
            b.spec_id,
            b.symbol,
            {
                key: _v(value.value, FieldProvenance.RESEARCH_CANDIDATE)
                for key, value in b.entry.items()
            },
            b.exit,
            b.filters,
            "different source text",
            b.created_at,
        )
        self.assertNotEqual(a.fingerprint, b.fingerprint)
        self.assertEqual(
            _strategy_semantic_fingerprint(a),
            _strategy_semantic_fingerprint(b),
        )

    def test_persistent_memory_skips_previous_variant_and_selects_next(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """
            CREATE TABLE research_memories(
                memory_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                strategy_family TEXT NOT NULL,
                market TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                final_status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source_run_id TEXT NOT NULL
            )
            """
        )
        base = _strategy("baseline:a", "2026-08-15T01:00:00Z")
        first, changes, semantic, skipped = _select_unique_adaptive_candidate(
            base,
            observed_failure="cost_fragile",
            iteration=1,
            known_semantic_fingerprints=set(),
        )
        self.assertIsNotNone(first)
        assert first is not None and semantic is not None
        self.assertEqual([], skipped)

        _remember_adaptive_candidate(
            connection,
            symbol="005930",
            observed_failure="cost_fragile",
            semantic_fingerprint=semantic,
            candidate=first,
            validation_status="cost_fragile",
            changed_rules=changes,
        )

        persisted = _persistent_adaptive_fingerprints(connection)
        self.assertIn(semantic, persisted)

        second, _, second_semantic, skipped = _select_unique_adaptive_candidate(
            base,
            observed_failure="cost_fragile",
            iteration=1,
            known_semantic_fingerprints=set(persisted),
        )
        self.assertIsNotNone(second)
        self.assertIn(semantic, skipped)
        self.assertNotEqual(semantic, second_semantic)

    def test_duplicate_variant_space_is_bounded(self) -> None:
        base = _strategy("baseline:a", "2026-08-15T01:00:00Z")
        known = set()
        for _ in range(4):
            candidate, _, semantic, _ = _select_unique_adaptive_candidate(
                base,
                observed_failure="cost_fragile",
                iteration=1,
                known_semantic_fingerprints=known,
            )
            self.assertIsNotNone(candidate)
            assert semantic is not None
            known.add(semantic)

        candidate, _, semantic, skipped = _select_unique_adaptive_candidate(
            base,
            observed_failure="cost_fragile",
            iteration=1,
            known_semantic_fingerprints=known,
        )
        self.assertIsNone(candidate)
        self.assertIsNone(semantic)
        self.assertEqual(4, len(skipped))


if __name__ == "__main__":
    unittest.main()
