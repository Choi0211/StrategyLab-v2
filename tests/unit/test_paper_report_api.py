"""HTTP-layer tests for ``POST /gaon/paper/report`` and
``GET /gaon/paper/summary`` - the Gaon<->Paper feedback-loop endpoints an
external execution engine (binance-trading's Paper loop) reports to and
reads from. These never mutate any ``strategy_version_registries`` row
and never require the approval-token machinery that mutating endpoints
like ``/gaon/strategy/version/activate`` need.

The one deliberate exception, tested separately below in
``RegisterHypothesisCandidateTests``: ``POST /gaon/paper/
hypothesis_register_candidate`` DOES write an APPLY_READY candidate to
``strategy_version_registries`` - but only ever APPLY_READY (never
ACTIVE), and only when derived from an already-recorded, verdict='pass'
row in this same module's own append-only backtest table - never from a
caller-supplied claim. See its adapter-method docstring in
``gaon.runtime.web_api`` for the full reasoning.
"""

from __future__ import annotations

import unittest

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.web_api import GaonWebChatAdapter, dispatch_request

FAMILY_ID = "csm-48h-long"

VALID_BODY = {
    "family_id": FAMILY_ID,
    "strategy_version_id": "strategy-version:abc123",
    "spec_fingerprint": "fp-csm48h-v1",
    "direction": "LONG",
    "symbol": "QNTUSDT",
    "signal_at": "2026-10-20T00:00:00Z",
    "status": "signal_only",
}


def _adapter(store: RuntimeStateStore) -> GaonWebChatAdapter:
    return GaonWebChatAdapter(GaonRuntimeConfig(assistant_enabled=False), store._connection)


class PaperReportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.adapter = _adapter(self.store)

    def test_valid_report_returns_200_with_observation_id(self) -> None:
        status, payload = dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=VALID_BODY)
        self.assertEqual(status, 200)
        self.assertIn("observation_id", payload)
        self.assertEqual(payload["family_id"], FAMILY_ID)
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])

    def test_missing_required_field_is_400(self) -> None:
        body = dict(VALID_BODY)
        del body["symbol"]
        status, payload = dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=body)
        self.assertEqual(status, 400)
        self.assertIn("symbol", payload["error"])

    def test_non_object_body_is_400(self) -> None:
        status, payload = dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=None)
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_closed_report_with_pnl_is_accepted(self) -> None:
        body = dict(VALID_BODY, status="closed", entry_at="t1", exit_at="t2", entry_price=1.0, exit_price=1.05, qty=10.0, pnl=0.5, pnl_pct=0.05, fees=0.01)
        status, payload = dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=body)
        self.assertEqual(status, 200)

    def test_resent_closed_report_returns_the_same_observation_id_not_a_duplicate(self) -> None:
        """A client retry after a lost response (schema v46's idempotency
        guard) must look identical to the caller - 200, same observation_id
        - not a 500 or a second row."""
        body = dict(VALID_BODY, status="closed", entry_at="t1", exit_at="t2", pnl=0.5, pnl_pct=0.05)
        status1, payload1 = dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=body)
        status2, payload2 = dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=dict(body))
        self.assertEqual((status1, status2), (200, 200))
        self.assertEqual(payload1["observation_id"], payload2["observation_id"])
        summary_status, summary = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/paper/summary?family_id={FAMILY_ID}", body=None
        )
        self.assertEqual(summary["aggregate"]["closed_trade_count"], 1)

    def test_summary_missing_family_id_is_400(self) -> None:
        status, payload = dispatch_request(self.adapter, method="GET", path="/gaon/paper/summary", body=None)
        self.assertEqual(status, 400)

    def test_summary_reflects_reported_observations(self) -> None:
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=VALID_BODY)
        closed = dict(VALID_BODY, status="closed", pnl=1.0, pnl_pct=0.01)
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=closed)

        status, payload = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/paper/summary?family_id={FAMILY_ID}", body=None
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["aggregate"]["closed_trade_count"], 1)
        self.assertEqual(len(payload["recent_observations"]), 2)
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])

    def test_summary_for_never_reported_family_is_empty_not_an_error(self) -> None:
        status, payload = dispatch_request(
            self.adapter, method="GET", path="/gaon/paper/summary?family_id=never-reported", body=None
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["aggregate"]["closed_trade_count"], 0)
        self.assertEqual(payload["recent_observations"], [])

    def test_routes_are_discoverable_from_root(self) -> None:
        status, payload = dispatch_request(self.adapter, method="GET", path="/", body=None)
        self.assertEqual(status, 200)
        self.assertEqual(payload["paper_report"], "/gaon/paper/report")
        self.assertEqual(payload["paper_summary"], "/gaon/paper/summary")
        self.assertEqual(payload["paper_failure_hypotheses"], "/gaon/paper/failure_hypotheses")
        self.assertEqual(payload["paper_hypothesis_backtest_result"], "/gaon/paper/hypothesis_backtest_result")
        self.assertEqual(payload["paper_hypothesis_backtests"], "/gaon/paper/hypothesis_backtests")
        self.assertEqual(payload["paper_failure_hypothesis_propose"], "/gaon/paper/failure_hypothesis")
        self.assertEqual(payload["paper_research_memories"], "/gaon/paper/research_memories")
        self.assertEqual(payload["paper_hypothesis_register_candidate"], "/gaon/paper/hypothesis_register_candidate")
        self.assertEqual(payload["mymoneyguard_status"], "/gaon/mymoneyguard/status")

    def test_propose_hypothesis_missing_required_field_is_400(self) -> None:
        status, payload = dispatch_request(
            self.adapter, method="POST", path="/gaon/paper/failure_hypothesis", body={"family_id": FAMILY_ID}
        )
        self.assertEqual(status, 400)

    def test_propose_hypothesis_valid_candidate_is_accepted_and_listed(self) -> None:
        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "hypothesis:x", "fingerprint": "sha256:refine1",
            "pattern_type": "symbol_concentration", "status": "candidate",
            "statement": "Backtest fold 2 shows PUMPUSDT at 30% concentration.",
            "trade_count": 130, "confidence": 0.5, "evidence": {"fold": 2, "top_symbol": "PUMPUSDT"},
            "verification_required": ["backtest with the symbol excluded"], "generated_at": "2026-10-20T00:00:00Z",
        }
        status, payload = dispatch_request(self.adapter, method="POST", path="/gaon/paper/failure_hypothesis", body=body)
        self.assertEqual(status, 200)
        self.assertIn("hypothesis_db_id", payload)
        self.assertFalse(payload["strategy_mutated"])

        status, listing = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/paper/failure_hypotheses?family_id={FAMILY_ID}", body=None
        )
        self.assertEqual(len(listing["hypotheses"]), 1)
        self.assertEqual(listing["hypotheses"][0]["pattern_type"], "symbol_concentration")

    def test_propose_hypothesis_resent_identical_fingerprint_is_idempotent(self) -> None:
        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "hypothesis:x", "fingerprint": "sha256:refine2",
            "pattern_type": "symbol_concentration", "status": "candidate", "statement": "x",
            "trade_count": 130, "evidence": {}, "verification_required": [], "generated_at": "2026-10-20T00:00:00Z",
        }
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/failure_hypothesis", body=dict(body))
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/failure_hypothesis", body=dict(body))
        status, listing = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/paper/failure_hypotheses?family_id={FAMILY_ID}", body=None
        )
        self.assertEqual(len(listing["hypotheses"]), 1)

    def test_propose_hypothesis_never_touches_strategy_version_registry(self) -> None:
        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "hypothesis:x", "fingerprint": "sha256:refine3",
            "pattern_type": "symbol_concentration", "status": "candidate", "statement": "x",
            "trade_count": 130, "evidence": {}, "verification_required": [], "generated_at": "2026-10-20T00:00:00Z",
        }
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/failure_hypothesis", body=body)
        version_status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertIsNone(version_status["active"])
        self.assertEqual(version_status["apply_ready"], [])

    def test_backtest_result_missing_required_field_is_400(self) -> None:
        status, payload = dispatch_request(
            self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result",
            body={"family_id": FAMILY_ID},
        )
        self.assertEqual(status, 400)

    def test_backtest_result_unrecognized_verdict_is_400(self) -> None:
        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "hypothesis:x", "hypothesis_fingerprint": "sha256:h",
            "backtest_fingerprint": "sha256:b", "verdict": "auto_promote", "metrics": {}, "data_source": "local",
            "tested_at": "2026-10-20T00:00:00Z",
        }
        status, payload = dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=body)
        self.assertEqual(status, 400)

    def test_backtest_result_valid_pass_is_accepted_and_listed(self) -> None:
        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "hypothesis:x", "hypothesis_fingerprint": "sha256:h",
            "backtest_fingerprint": "sha256:b", "verdict": "pass",
            "metrics": {"oos_pf": 1.5, "oos_n": 110}, "data_source": "local_1m_kline_cache",
            "oos_validated": True, "tested_at": "2026-10-20T00:00:00Z",
        }
        status, payload = dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=body)
        self.assertEqual(status, 200)
        self.assertIn("backtest_id", payload)
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["champion_promoted"])

        status, listing = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/paper/hypothesis_backtests?family_id={FAMILY_ID}", body=None
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["backtests"]), 1)
        self.assertEqual(len(listing["passed_pending_revalidation"]), 1)

    def test_backtest_result_writes_a_discoverable_research_memory(self) -> None:
        """Closes the auto-cycle: a reported backtest result must also
        land in research_memories so the next research cycle can find it
        via the existing research_memory_search tool - not just sit in
        the structured table unseen."""
        from gaon.research.self_improving import SQLiteResearchMemoryRepository

        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "baseline_validation:csm-48h-long",
            "hypothesis_fingerprint": "baseline:csm-48h-long", "backtest_fingerprint": "sha256:mem1",
            "verdict": "pass", "metrics": {"overall": {"pf": 1.56, "n": 500}},
            "data_source": "local_1m_kline_cache", "oos_validated": True, "tested_at": "2026-10-20T00:00:00Z",
        }
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=body)
        memories = SQLiteResearchMemoryRepository(self.store._connection).search(tag=FAMILY_ID)
        self.assertEqual(len(memories), 1)
        self.assertIn("pass", memories[0].result_summary)
        self.assertEqual(memories[0].final_status, "PENDING_HUMAN_REVIEW")
        self.assertIn("never auto-activated", memories[0].improvement_summary)

    def test_resent_backtest_result_does_not_duplicate_the_research_memory(self) -> None:
        from gaon.research.self_improving import SQLiteResearchMemoryRepository

        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "x", "hypothesis_fingerprint": "sha256:h",
            "backtest_fingerprint": "sha256:mem2", "verdict": "fail", "metrics": {},
            "data_source": "local", "tested_at": "2026-10-20T00:00:00Z",
        }
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=dict(body))
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=dict(body))
        memories = SQLiteResearchMemoryRepository(self.store._connection).search(tag=FAMILY_ID)
        self.assertEqual(len(memories), 1)

    def test_research_memories_endpoint_requires_family_id(self) -> None:
        status, payload = dispatch_request(self.adapter, method="GET", path="/gaon/paper/research_memories", body=None)
        self.assertEqual(status, 400)

    def test_research_memories_endpoint_returns_recorded_backtest_memories_newest_first(self) -> None:
        for i, (fingerprint, verdict) in enumerate((("sha256:older", "fail"), ("sha256:newer", "pass"))):
            body = {
                "family_id": FAMILY_ID, "hypothesis_id": f"hypothesis:{i}", "hypothesis_fingerprint": f"sha256:hyp{i}",
                "backtest_fingerprint": fingerprint, "verdict": verdict, "metrics": {},
                "data_source": "local", "tested_at": f"2026-10-2{i}T00:00:00Z",
            }
            status, _ = dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=body)
            self.assertEqual(status, 200)
        status, payload = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/paper/research_memories?family_id={FAMILY_ID}", body=None
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["memories"]), 2)
        self.assertEqual(payload["memories"][0]["final_status"], "PENDING_HUMAN_REVIEW")  # newer (verdict=pass) first
        self.assertEqual(payload["memories"][1]["final_status"], "FAIL")
        self.assertFalse(payload["strategy_mutated"])

    def test_research_memories_endpoint_exposes_hypothesis_fingerprint_tag(self) -> None:
        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "hypothesis:x", "hypothesis_fingerprint": "sha256:findme",
            "backtest_fingerprint": "sha256:tagtest", "verdict": "fail", "metrics": {},
            "data_source": "local", "tested_at": "2026-10-20T00:00:00Z",
        }
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=body)
        _, payload = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/paper/research_memories?family_id={FAMILY_ID}", body=None
        )
        self.assertIn("hypothesis_fingerprint:sha256:findme", payload["memories"][0]["tags"])

    def test_research_memories_endpoint_respects_limit(self) -> None:
        for i in range(3):
            body = {
                "family_id": FAMILY_ID, "hypothesis_id": f"hypothesis:{i}", "hypothesis_fingerprint": f"sha256:hyp{i}",
                "backtest_fingerprint": f"sha256:limit{i}", "verdict": "fail", "metrics": {},
                "data_source": "local", "tested_at": f"2026-10-2{i}T00:00:00Z",
            }
            dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=body)
        _, payload = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/paper/research_memories?family_id={FAMILY_ID}&limit=2", body=None
        )
        self.assertEqual(len(payload["memories"]), 2)

    def test_research_memories_endpoint_never_touches_strategy_version_registry(self) -> None:
        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "hypothesis:x", "hypothesis_fingerprint": "sha256:h",
            "backtest_fingerprint": "sha256:regtest", "verdict": "pass", "metrics": {},
            "data_source": "local", "tested_at": "2026-10-20T00:00:00Z",
        }
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=body)
        dispatch_request(self.adapter, method="GET", path=f"/gaon/paper/research_memories?family_id={FAMILY_ID}", body=None)
        version_status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertIsNone(version_status["active"])
        self.assertEqual(version_status["apply_ready"], [])

    def test_backtest_result_never_touches_strategy_version_registry(self) -> None:
        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "hypothesis:x", "hypothesis_fingerprint": "sha256:h",
            "backtest_fingerprint": "sha256:b", "verdict": "pass", "metrics": {}, "data_source": "local",
            "tested_at": "2026-10-20T00:00:00Z",
        }
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=body)
        version_status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertIsNone(version_status["active"])
        self.assertEqual(version_status["apply_ready"], [])

    def test_failure_hypotheses_missing_family_id_is_400(self) -> None:
        status, payload = dispatch_request(self.adapter, method="GET", path="/gaon/paper/failure_hypotheses", body=None)
        self.assertEqual(status, 400)

    def test_failure_hypotheses_empty_for_a_family_with_no_hypotheses_yet(self) -> None:
        status, payload = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/paper/failure_hypotheses?family_id={FAMILY_ID}", body=None
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["hypotheses"], [])
        self.assertFalse(payload["strategy_mutated"])

    def test_report_never_touches_strategy_version_registry(self) -> None:
        """The whole point of keeping this ledger separate: reporting Paper
        results must never flip any ACTIVE strategy-version state."""
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=VALID_BODY)
        version_status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertIsNone(version_status["active"])
        self.assertEqual(version_status["apply_ready"], [])


class RegisterHypothesisCandidateTests(unittest.TestCase):
    """POST /gaon/paper/hypothesis_register_candidate is the one
    deliberate exception to 'this module never touches
    strategy_version_registries' - see its own adapter-method docstring.
    It only ever creates an APPLY_READY candidate (never ACTIVE), and only
    from an already-recorded, verdict='pass' backtest row - never from a
    caller-supplied claim."""

    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.adapter = _adapter(self.store)

    def _report_passing_backtest(self, **overrides) -> dict:
        body = {
            "family_id": FAMILY_ID, "hypothesis_id": "hypothesis:csm-48h-long:x:abc",
            "hypothesis_fingerprint": "sha256:hyp-abc", "backtest_fingerprint": "sha256:bt-abc",
            "verdict": "pass", "metrics": {"oos_pf": 1.6, "oos_n": 120},
            "data_source": "local_1m_kline_cache", "data_period_start": "2026-03-01T00:00:00Z",
            "data_period_end": "2026-09-28T23:59:00Z", "symbols_processed": 23,
            "fee_assumption_pct": 0.30, "oos_validated": True, "tested_at": "2026-10-20T00:00:00Z",
        }
        body.update(overrides)
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_backtest_result", body=body)
        return body

    def test_requires_family_id_and_backtest_fingerprint(self) -> None:
        status, payload = dispatch_request(
            self.adapter, method="POST", path="/gaon/paper/hypothesis_register_candidate", body={}
        )
        self.assertEqual(status, 400)

    def test_unknown_backtest_fingerprint_is_rejected(self) -> None:
        status, payload = dispatch_request(
            self.adapter, method="POST", path="/gaon/paper/hypothesis_register_candidate",
            body={"family_id": FAMILY_ID, "backtest_fingerprint": "sha256:never-reported"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_non_passing_verdict_is_rejected(self) -> None:
        self._report_passing_backtest(backtest_fingerprint="sha256:failed-one", verdict="fail", hypothesis_fingerprint="sha256:hyp-failed")
        status, payload = dispatch_request(
            self.adapter, method="POST", path="/gaon/paper/hypothesis_register_candidate",
            body={"family_id": FAMILY_ID, "backtest_fingerprint": "sha256:failed-one"},
        )
        self.assertEqual(status, 400)

    def test_passing_backtest_registers_an_apply_ready_candidate(self) -> None:
        self._report_passing_backtest()
        status, payload = dispatch_request(
            self.adapter, method="POST", path="/gaon/paper/hypothesis_register_candidate",
            body={"family_id": FAMILY_ID, "backtest_fingerprint": "sha256:bt-abc", "direction": "LONG"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "apply_ready")
        self.assertFalse(payload["already_registered"])
        self.assertTrue(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        version_status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertIsNone(version_status["active"])  # still never auto-activated
        self.assertEqual(len(version_status["apply_ready"]), 1)

    def test_resending_the_same_finding_is_idempotent_not_a_duplicate(self) -> None:
        self._report_passing_backtest()
        body = {"family_id": FAMILY_ID, "backtest_fingerprint": "sha256:bt-abc", "direction": "LONG"}
        first_status, first = dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_register_candidate", body=body)
        second_status, second = dispatch_request(self.adapter, method="POST", path="/gaon/paper/hypothesis_register_candidate", body=dict(body))
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first["strategy_version_id"], second["strategy_version_id"])
        self.assertFalse(first["already_registered"])
        self.assertTrue(second["already_registered"])
        version_status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertEqual(len(version_status["apply_ready"]), 1)

    def test_never_marks_anything_active_by_itself(self) -> None:
        self._report_passing_backtest()
        dispatch_request(
            self.adapter, method="POST", path="/gaon/paper/hypothesis_register_candidate",
            body={"family_id": FAMILY_ID, "backtest_fingerprint": "sha256:bt-abc"},
        )
        version_status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertIsNone(version_status["active"])
        self.assertIsNone(version_status["active_by_direction"]["LONG"])
        self.assertIsNone(version_status["active_by_direction"]["SHORT"])


class MyMoneyGuardStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.adapter = _adapter(self.store)

    def test_missing_snapshot_is_reported_honestly_not_fabricated(self) -> None:
        import gaon.adapters.mymoneyguard as mmg_module
        from unittest.mock import patch

        with patch.object(mmg_module, "DEFAULT_SNAPSHOT_PATH", "/nonexistent/path/snapshot.json"):
            status, payload = dispatch_request(self.adapter, method="GET", path="/gaon/mymoneyguard/status", body=None)
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])
        self.assertFalse(payload["order_execution_connected"] if "order_execution_connected" in payload else False)

    def test_route_never_touches_strategy_version_registry(self) -> None:
        dispatch_request(self.adapter, method="GET", path="/gaon/mymoneyguard/status", body=None)
        version_status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertIsNone(version_status["active"])


if __name__ == "__main__":
    unittest.main()
