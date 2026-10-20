"""HTTP-layer tests for ``POST /gaon/paper/report`` and
``GET /gaon/paper/summary`` - the Gaon<->Paper feedback-loop endpoints an
external execution engine (binance-trading's Paper loop) reports to and
reads from. These never mutate any ``strategy_version_registries`` row
and never require the approval-token machinery that mutating endpoints
like ``/gaon/strategy/version/activate`` need.
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

    def test_report_never_touches_strategy_version_registry(self) -> None:
        """The whole point of keeping this ledger separate: reporting Paper
        results must never flip any ACTIVE strategy-version state."""
        dispatch_request(self.adapter, method="POST", path="/gaon/paper/report", body=VALID_BODY)
        version_status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertIsNone(version_status["active"])
        self.assertEqual(version_status["apply_ready"], [])


if __name__ == "__main__":
    unittest.main()
