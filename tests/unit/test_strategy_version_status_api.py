"""Acceptance tests for feature/gaon-market-context-and-strategy-rollback-contract.

Problem B: ``GET /gaon/strategy/version_status`` must report TRUTHFUL
ACTIVE/PREVIOUS strategy-version state from the canonical
``StrategyVersionRegistry``/``StrategyConsoleReadModel`` read-model
(``gaon.control.strategy_version``/``gaon.control.strategy_console``) -
``available_for_rollback`` must be False when no genuine PREVIOUS version
exists, and only True once one actually does, durably (surviving a fresh
connection/process), never based on a backup-file-existence guess. This is
the contract the separate Binance dashboard's
``/api/strategy_params/backup_status`` should be built against - see
``docs/architecture/GaonStrategyRollbackContract.md``.
"""

from __future__ import annotations

import unittest

from gaon.control.strategy_version import StrategyVersionRegistry
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.migrations import SCHEMA_VERSION
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.strategy_version_repository import StrategyVersionSQLiteRepository
from gaon.runtime.web_api import GaonWebChatAdapter, dispatch_request

NOW = "2026-09-14T00:00:00Z"
LATER = "2026-09-15T00:00:00Z"
FAMILY_ID = "binance-price-action"


def _adapter(store: RuntimeStateStore) -> GaonWebChatAdapter:
    return GaonWebChatAdapter(GaonRuntimeConfig(assistant_enabled=False), store._connection)


class StrategyVersionStatusTruthfulnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.adapter = _adapter(self.store)

    def test_no_versions_reports_false_available_for_rollback_and_no_active(self) -> None:
        """No backup file existing today makes the OLD Binance dashboard
        API hide the button; this canonical contract must reach the same
        honest answer for genuinely no history, but by asking the real
        registry, not a file-existence proxy."""
        status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertFalse(status["available_for_rollback"])
        self.assertIsNone(status["active"])
        self.assertEqual(status["previous"], [])

    def test_single_active_version_still_reports_false_available_for_rollback(self) -> None:
        """A single APPLY_READY version promoted straight to ACTIVE, with
        nothing ever demoted to PREVIOUS, must NOT falsely advertise a
        rollback target - there genuinely is nothing to roll back to yet."""
        registry = StrategyVersionRegistry()
        version = registry.register_apply_ready(
            family_id=FAMILY_ID, candidate_id="c1", spec_fingerprint="fp1",
            spec_rules={"entry": "breakout"}, validation_summary={"trades": 40}, at=NOW,
        )
        registry.mark_active(version.strategy_version_id, at=NOW)
        StrategyVersionSQLiteRepository(self.store._connection).save(FAMILY_ID, registry, now=NOW)

        status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertFalse(status["available_for_rollback"])
        self.assertIsNotNone(status["active"])
        self.assertEqual(status["active"]["strategy_version_id"], version.strategy_version_id)
        self.assertEqual(status["previous"], [])

    def test_second_activation_creates_genuine_previous_and_flips_available_true(self) -> None:
        """Only once a SECOND version is actually activated (demoting the
        first to PREVIOUS) does a real rollback target exist - this is the
        exact moment ``available_for_rollback`` must become truthfully
        True."""
        registry = StrategyVersionRegistry()
        v1 = registry.register_apply_ready(
            family_id=FAMILY_ID, candidate_id="c1", spec_fingerprint="fp1",
            spec_rules={"entry": "breakout"}, validation_summary={"trades": 40}, at=NOW,
        )
        registry.mark_active(v1.strategy_version_id, at=NOW)
        v2 = registry.register_apply_ready(
            family_id=FAMILY_ID, candidate_id="c2", spec_fingerprint="fp2",
            spec_rules={"entry": "mean_reversion"}, validation_summary={"trades": 55}, at=LATER,
        )
        registry.mark_active(v2.strategy_version_id, at=LATER)
        StrategyVersionSQLiteRepository(self.store._connection).save(FAMILY_ID, registry, now=LATER)

        status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertTrue(status["available_for_rollback"])
        self.assertEqual(status["active"]["strategy_version_id"], v2.strategy_version_id)
        previous_ids = [p["strategy_version_id"] for p in status["previous"]]
        self.assertEqual(previous_ids, [v1.strategy_version_id])
        rollback_actions = [a for a in status["actions"] if a["action"] == "rollback"]
        self.assertEqual([a["strategy_version_id"] for a in rollback_actions], [v1.strategy_version_id])

    def test_retired_version_is_never_offered_as_a_rollback_target(self) -> None:
        registry = StrategyVersionRegistry()
        v1 = registry.register_apply_ready(
            family_id=FAMILY_ID, candidate_id="c1", spec_fingerprint="fp1",
            spec_rules={}, validation_summary={}, at=NOW,
        )
        registry.mark_active(v1.strategy_version_id, at=NOW)
        v2 = registry.register_apply_ready(
            family_id=FAMILY_ID, candidate_id="c2", spec_fingerprint="fp2",
            spec_rules={}, validation_summary={}, at=LATER,
        )
        registry.mark_active(v2.strategy_version_id, at=LATER)
        registry.mark_retired(v1.strategy_version_id, at=LATER, reason="superseded")
        StrategyVersionSQLiteRepository(self.store._connection).save(FAMILY_ID, registry, now=LATER)

        status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertFalse(status["available_for_rollback"])
        self.assertEqual(status["previous"], [])
        self.assertEqual(len(status["retired"]), 1)

    def test_status_is_durable_across_a_fresh_connection_handle(self) -> None:
        """Proves this is real persistence, not an in-memory artifact of
        one adapter instance - a fresh GaonWebChatAdapter over the SAME
        underlying connection (simulating a later HTTP request / process)
        must see the identical truthful state."""
        registry = StrategyVersionRegistry()
        v1 = registry.register_apply_ready(family_id=FAMILY_ID, candidate_id="c1", spec_fingerprint="fp1", spec_rules={}, validation_summary={}, at=NOW)
        registry.mark_active(v1.strategy_version_id, at=NOW)
        v2 = registry.register_apply_ready(family_id=FAMILY_ID, candidate_id="c2", spec_fingerprint="fp2", spec_rules={}, validation_summary={}, at=LATER)
        registry.mark_active(v2.strategy_version_id, at=LATER)
        StrategyVersionSQLiteRepository(self.store._connection).save(FAMILY_ID, registry, now=LATER)

        fresh_adapter = _adapter(self.store)
        status = fresh_adapter.strategy_version_status(FAMILY_ID)
        self.assertTrue(status["available_for_rollback"])

    def test_different_families_are_isolated(self) -> None:
        registry = StrategyVersionRegistry()
        v1 = registry.register_apply_ready(family_id=FAMILY_ID, candidate_id="c1", spec_fingerprint="fp1", spec_rules={}, validation_summary={}, at=NOW)
        registry.mark_active(v1.strategy_version_id, at=NOW)
        v2 = registry.register_apply_ready(family_id=FAMILY_ID, candidate_id="c2", spec_fingerprint="fp2", spec_rules={}, validation_summary={}, at=LATER)
        registry.mark_active(v2.strategy_version_id, at=LATER)
        StrategyVersionSQLiteRepository(self.store._connection).save(FAMILY_ID, registry, now=LATER)

        other_status = self.adapter.strategy_version_status("kr-breakout-standard")
        self.assertFalse(other_status["available_for_rollback"])
        self.assertIsNone(other_status["active"])

    def test_never_reports_live_or_order_or_promotion_mutation(self) -> None:
        status = self.adapter.strategy_version_status(FAMILY_ID)
        self.assertFalse(status["strategy_mutated"])
        self.assertFalse(status["order_executed"])
        self.assertFalse(status["champion_promoted"])
        self.assertFalse(status["live_activated"])
        self.assertFalse(status["approval_bypassed"])


class StrategyVersionStatusHttpWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.adapter = _adapter(self.store)

    def test_missing_family_id_is_400(self) -> None:
        status, payload = dispatch_request(self.adapter, method="GET", path="/gaon/strategy/version_status", body=None)
        self.assertEqual(status, 400)
        self.assertIn("family_id", payload["error"])

    def test_get_with_family_id_returns_200_and_route_is_discoverable(self) -> None:
        status, payload = dispatch_request(
            self.adapter, method="GET", path=f"/gaon/strategy/version_status?family_id={FAMILY_ID}", body=None
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["family_id"], FAMILY_ID)
        self.assertFalse(payload["available_for_rollback"])

        root_status, root_payload = dispatch_request(self.adapter, method="GET", path="/", body=None)
        self.assertEqual(root_status, 200)
        self.assertEqual(root_payload["strategy_version_status"], "/gaon/strategy/version_status")


class StrategyVersionSchemaTests(unittest.TestCase):
    def test_schema_version_is_current(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 43)


if __name__ == "__main__":
    unittest.main()
