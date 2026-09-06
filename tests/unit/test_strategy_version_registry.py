"""Priority 2 / D1 + D4 - immutable strategy version registry.

Applying a strategy does NOT overwrite the previous one - every version
is an immutable record kept in history. No candidate / spec / validation
/ activation record is ever deleted; the full history is auditable.

Statuses: APPLY_READY -> ACTIVE ; the prior ACTIVE becomes PREVIOUS ;
a PREVIOUS/RETIRED version can be re-activated (rollback) and RETIRED is
terminal-ish (a retired version is not offered for activation).

Isolated module (gaon.control.strategy_version) - no production wiring,
no change to existing mission/candidate identity.
"""

from __future__ import annotations

import unittest

from gaon.control.strategy_version import (
    StrategyVersion,
    StrategyVersionRegistry,
    StrategyVersionStatus,
)

T = "2026-09-06T00:00:00Z"


def _register(reg, *, fingerprint, candidate_id, at):
    return reg.register_apply_ready(
        family_id="mean_reversion_standard",
        candidate_id=candidate_id,
        spec_fingerprint=fingerprint,
        spec_rules={"entry": {"mean_reversion_ma_lookback": {"value": 20}}},
        validation_summary={"trade_count": 42, "profit_factor": 1.3, "status": "pass"},
        at=at,
    )


class RegisterAndListTests(unittest.TestCase):
    def test_register_apply_ready_creates_an_immutable_record(self) -> None:
        reg = StrategyVersionRegistry()
        v = _register(reg, fingerprint="fp-a", candidate_id="KR-ST-010", at=T)
        self.assertIsInstance(v, StrategyVersion)
        self.assertEqual(v.status, StrategyVersionStatus.APPLY_READY)
        self.assertEqual(v.spec_fingerprint, "fp-a")
        self.assertIsNone(v.activated_at)
        with self.assertRaises(Exception):
            v.status = StrategyVersionStatus.ACTIVE  # frozen

    def test_history_lists_every_registered_version_newest_last(self) -> None:
        reg = StrategyVersionRegistry()
        _register(reg, fingerprint="fp-a", candidate_id="KR-ST-010", at="2026-09-06T00:00:00Z")
        _register(reg, fingerprint="fp-b", candidate_id="KR-ST-011", at="2026-09-06T01:00:00Z")
        history = reg.history()
        self.assertEqual([h.spec_fingerprint for h in history], ["fp-a", "fp-b"])


class ActivationTransitionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reg = StrategyVersionRegistry()
        self.a = _register(self.reg, fingerprint="fp-a", candidate_id="KR-ST-010", at="2026-09-06T00:00:00Z")
        self.b = _register(self.reg, fingerprint="fp-b", candidate_id="KR-ST-011", at="2026-09-06T01:00:00Z")

    def test_activating_sets_active_and_leaves_no_prior_active(self) -> None:
        self.reg.mark_active(self.a.strategy_version_id, at="2026-09-06T02:00:00Z")
        self.assertEqual(self.reg.active().spec_fingerprint, "fp-a")
        self.assertEqual(self.reg.active().status, StrategyVersionStatus.ACTIVE)
        self.assertIsNotNone(self.reg.active().activated_at)

    def test_activating_a_second_version_demotes_the_first_to_previous(self) -> None:
        self.reg.mark_active(self.a.strategy_version_id, at="2026-09-06T02:00:00Z")
        self.reg.mark_active(self.b.strategy_version_id, at="2026-09-06T03:00:00Z")
        self.assertEqual(self.reg.active().spec_fingerprint, "fp-b")
        prior = self.reg.get(self.a.strategy_version_id)
        self.assertEqual(prior.status, StrategyVersionStatus.PREVIOUS)
        self.assertIsNotNone(prior.deactivated_at)
        # exactly one ACTIVE at all times.
        self.assertEqual(sum(1 for h in self.reg.history() if h.status == StrategyVersionStatus.ACTIVE), 1)

    def test_a_previous_version_can_be_reactivated_rollback(self) -> None:
        self.reg.mark_active(self.a.strategy_version_id, at="2026-09-06T02:00:00Z")
        self.reg.mark_active(self.b.strategy_version_id, at="2026-09-06T03:00:00Z")
        self.reg.mark_active(self.a.strategy_version_id, at="2026-09-06T04:00:00Z")
        self.assertEqual(self.reg.active().spec_fingerprint, "fp-a")
        self.assertEqual(self.reg.get(self.b.strategy_version_id).status, StrategyVersionStatus.PREVIOUS)

    def test_retired_version_is_not_activatable(self) -> None:
        self.reg.mark_retired(self.a.strategy_version_id, at="2026-09-06T02:00:00Z", reason="superseded")
        with self.assertRaises(ValueError):
            self.reg.mark_active(self.a.strategy_version_id, at="2026-09-06T03:00:00Z")

    def test_activating_an_unknown_version_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.reg.mark_active("strategy-version:nope", at=T)


class NoDestructiveHistoryTests(unittest.TestCase):
    def test_registry_exposes_no_delete_or_purge(self) -> None:
        names = set(dir(StrategyVersionRegistry))
        for banned in ("delete", "remove", "purge", "clear", "drop", "overwrite"):
            self.assertNotIn(banned, names)

    def test_json_round_trip_preserves_the_full_history(self) -> None:
        reg = StrategyVersionRegistry()
        _register(reg, fingerprint="fp-a", candidate_id="KR-ST-010", at="2026-09-06T00:00:00Z")
        b = _register(reg, fingerprint="fp-b", candidate_id="KR-ST-011", at="2026-09-06T01:00:00Z")
        reg.mark_active(b.strategy_version_id, at="2026-09-06T02:00:00Z")
        again = StrategyVersionRegistry.from_json(reg.to_json())
        self.assertEqual([h.to_json() for h in again.history()], [h.to_json() for h in reg.history()])
        self.assertEqual(again.active().spec_fingerprint, "fp-b")


if __name__ == "__main__":
    unittest.main()
