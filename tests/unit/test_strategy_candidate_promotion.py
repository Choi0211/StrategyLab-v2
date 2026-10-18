import json
import unittest

from gaon.control.strategy_candidate_promotion import (
    evaluate_run,
    list_promotable_candidates,
    promote_eligible_candidates,
)
from gaon.control.strategy_version import StrategyVersionStatus
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.strategy_version_repository import StrategyVersionSQLiteRepository

T = "2026-10-19T00:00:00Z"

GOOD_SUMMARY = {
    "sample_confidence": "high",
    "concentration_decision": "broad",
    "aggregate_trade_count": 60,
    "profitable_symbol_ratio": 0.75,
    "median_return": 0.12,
}

STRATEGY = {
    "fingerprint": "fp-good-1",
    "entry": {"mean_reversion_band_pct": 5.0},
    "exit": {"protective_stop_pct": -5.0},
    "filters": {},
}


def _payload(run_id, *, recommendation="candidate_preferred", summary=None, strategy=None):
    return {
        "run_id": run_id,
        "final_recommendation": recommendation,
        "summary": GOOD_SUMMARY if summary is None else summary,
        "strategy": STRATEGY if strategy is None else strategy,
    }


def _insert_run(connection, run_id, payload, *, artifact=False):
    rid = run_id if not artifact else f"multi-symbol-research-demo:{run_id}"
    connection.execute(
        """
        INSERT OR REPLACE INTO multi_symbol_research_runs(
            run_id, universe_id, status, recommendation, payload_json, generated_at, source
        ) VALUES (?, ?, 'completed', ?, ?, ?, 'real')
        """,
        (rid, "universe:test", payload.get("final_recommendation"), json.dumps({**payload, "run_id": rid}), T),
    )
    connection.commit()


class EvaluateRunTests(unittest.TestCase):
    def test_good_candidate_is_eligible(self):
        decision = evaluate_run(_payload("r1"))
        self.assertTrue(decision.eligible)
        self.assertIsNotNone(decision.family_id)
        self.assertEqual(decision.spec_fingerprint, "fp-good-1")

    def test_relative_recommendation_alone_is_not_enough(self):
        summary = {**GOOD_SUMMARY, "median_return": -0.3, "profitable_symbol_ratio": 0.25}
        decision = evaluate_run(_payload("r2", summary=summary))
        self.assertFalse(decision.eligible)
        self.assertIn("profitable", decision.reason)

    def test_non_preferred_recommendation_rejected(self):
        decision = evaluate_run(_payload("r3", recommendation="no_clear_winner"))
        self.assertFalse(decision.eligible)

    def test_low_confidence_rejected(self):
        summary = {**GOOD_SUMMARY, "sample_confidence": "medium"}
        decision = evaluate_run(_payload("r4", summary=summary))
        self.assertFalse(decision.eligible)

    def test_concentrated_rejected(self):
        summary = {**GOOD_SUMMARY, "concentration_decision": "highly_concentrated"}
        decision = evaluate_run(_payload("r5", summary=summary))
        self.assertFalse(decision.eligible)

    def test_thin_sample_rejected(self):
        summary = {**GOOD_SUMMARY, "aggregate_trade_count": 5}
        decision = evaluate_run(_payload("r6", summary=summary))
        self.assertFalse(decision.eligible)

    def test_zero_median_return_rejected(self):
        summary = {**GOOD_SUMMARY, "median_return": 0.0}
        decision = evaluate_run(_payload("r7", summary=summary))
        self.assertFalse(decision.eligible)

    def test_missing_fingerprint_rejected(self):
        decision = evaluate_run(_payload("r8", strategy={**STRATEGY, "fingerprint": ""}))
        self.assertFalse(decision.eligible)

    def test_same_strategy_shape_shares_family(self):
        d1 = evaluate_run(_payload("r9"))
        d2 = evaluate_run(_payload("r10", strategy={**STRATEGY, "fingerprint": "fp-good-2"}))
        self.assertEqual(d1.family_id, d2.family_id)


class PromoteEligibleCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.connection = self.store._connection

    def test_promotes_only_genuinely_eligible_runs(self):
        _insert_run(self.connection, "multi-symbol-research:good1", _payload("multi-symbol-research:good1"))
        losing_summary = {**GOOD_SUMMARY, "median_return": -0.1, "profitable_symbol_ratio": 0.2}
        _insert_run(self.connection, "multi-symbol-research:bad1", _payload("multi-symbol-research:bad1", summary=losing_summary))

        registered = promote_eligible_candidates(self.connection, now=T)

        self.assertEqual(len(registered), 1)
        self.assertEqual(registered[0].candidate_id, "multi-symbol-research:good1")
        self.assertEqual(registered[0].status, StrategyVersionStatus.APPLY_READY)
        self.assertIsNone(registered[0].direction)

    def test_excludes_release_check_artifacts(self):
        _insert_run(self.connection, "artifact1", _payload("artifact1"), artifact=True)
        registered = promote_eligible_candidates(self.connection, now=T)
        self.assertEqual(registered, ())

    def test_idempotent_no_duplicate_registration(self):
        _insert_run(self.connection, "multi-symbol-research:dup1", _payload("multi-symbol-research:dup1"))
        first = promote_eligible_candidates(self.connection, now=T)
        second = promote_eligible_candidates(self.connection, now=T)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())

        repo = StrategyVersionSQLiteRepository(self.connection)
        registry = repo.get(first[0].family_id)
        self.assertEqual(len(registry.history()), 1)

    def test_never_activates_anything(self):
        _insert_run(self.connection, "multi-symbol-research:good2", _payload("multi-symbol-research:good2"))
        registered = promote_eligible_candidates(self.connection, now=T)
        repo = StrategyVersionSQLiteRepository(self.connection)
        registry = repo.get(registered[0].family_id)
        self.assertIsNone(registry.active())

    def test_list_promotable_candidates_reports_rejections_too(self):
        losing_summary = {**GOOD_SUMMARY, "median_return": -0.1, "profitable_symbol_ratio": 0.2}
        _insert_run(self.connection, "multi-symbol-research:bad2", _payload("multi-symbol-research:bad2", summary=losing_summary))
        decisions = list_promotable_candidates(self.connection)
        self.assertEqual(len(decisions), 1)
        self.assertFalse(decisions[0].eligible)


if __name__ == "__main__":
    unittest.main()
