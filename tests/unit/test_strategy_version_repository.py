"""Tests for gaon.runtime.strategy_version_repository - the SQLite
durability layer for StrategyVersionRegistry (previously in-memory-only)."""

from __future__ import annotations

import sqlite3
import unittest

from gaon.control.strategy_version import StrategyVersionRegistry, StrategyVersionStatus
from gaon.runtime.migrations import migrate
from gaon.runtime.strategy_version_repository import StrategyVersionSQLiteRepository

NOW = "2026-09-14T00:00:00Z"


class StrategyVersionSQLiteRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.repo = StrategyVersionSQLiteRepository(self.connection)

    def test_get_unknown_family_returns_empty_registry_not_an_error(self) -> None:
        registry = self.repo.get("never-seen-family")
        self.assertEqual(registry.history(), [])
        self.assertIsNone(registry.active())

    def test_save_then_get_round_trips_exactly(self) -> None:
        registry = StrategyVersionRegistry()
        version = registry.register_apply_ready(
            family_id="binance-price-action", candidate_id="c1", spec_fingerprint="fp1",
            spec_rules={"entry": {"lookback": 20}}, validation_summary={"trades": 12}, at=NOW,
        )
        registry.mark_active(version.strategy_version_id, at=NOW)
        self.repo.save("binance-price-action", registry, now=NOW)

        reloaded = self.repo.get("binance-price-action")
        active = reloaded.active()
        self.assertIsNotNone(active)
        self.assertEqual(active.strategy_version_id, version.strategy_version_id)
        self.assertEqual(active.status, StrategyVersionStatus.ACTIVE)
        self.assertEqual(dict(active.spec_rules), {"entry": {"lookback": 20}})

    def test_save_overwrites_the_same_family_idempotently(self) -> None:
        registry = StrategyVersionRegistry()
        v1 = registry.register_apply_ready(family_id="f", candidate_id="c1", spec_fingerprint="fp1", spec_rules={}, validation_summary={}, at=NOW)
        registry.mark_active(v1.strategy_version_id, at=NOW)
        self.repo.save("f", registry, now=NOW)
        self.repo.save("f", registry, now=NOW)  # idempotent re-save

        rows = self.connection.execute("SELECT COUNT(*) FROM strategy_version_registries WHERE family_id='f'").fetchone()[0]
        self.assertEqual(rows, 1)

    def test_families_are_isolated_from_each_other(self) -> None:
        registry_a = StrategyVersionRegistry()
        va = registry_a.register_apply_ready(family_id="a", candidate_id="c1", spec_fingerprint="fp1", spec_rules={}, validation_summary={}, at=NOW)
        registry_a.mark_active(va.strategy_version_id, at=NOW)
        self.repo.save("a", registry_a, now=NOW)

        registry_b = self.repo.get("b")
        self.assertEqual(registry_b.history(), [])


if __name__ == "__main__":
    unittest.main()
