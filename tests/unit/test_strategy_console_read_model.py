"""Priority 3 - the server-side read model behind the Web strategy console.

The proposal panel COLLAPSES / EXPANDS; it is never dismissed
(destroyed). Its open/closed state and everything the console shows
(ACTIVE / APPLY_READY / PREVIOUS / RETIRED versions, and which can be
applied or rolled back to) come from this backend read model, so a
browser reload - or a second browser - sees the same thing.
"""

from __future__ import annotations

import json
import unittest

from gaon.control.strategy_console import (
    ProposalPanelState,
    ProposalPanelStore,
    StrategyConsoleReadModel,
)
from gaon.control.strategy_version import StrategyVersionRegistry, StrategyVersionStatus


def _registry() -> StrategyVersionRegistry:
    reg = StrategyVersionRegistry()
    reg.register_apply_ready(
        family_id="breakout_standard", candidate_id="cand-a", spec_fingerprint="fp-a",
        spec_rules={"entry": {"breakout_lookback": 20}}, validation_summary={"passed": True}, at="2026-01-01T00:00:00Z",
    )
    reg.register_apply_ready(
        family_id="breakout_standard", candidate_id="cand-b", spec_fingerprint="fp-b",
        spec_rules={"entry": {"breakout_lookback": 30}}, validation_summary={"passed": True}, at="2026-01-02T00:00:00Z",
    )
    return reg


class ProposalPanelStateTests(unittest.TestCase):
    def test_default_is_expanded(self) -> None:
        store = ProposalPanelStore()
        self.assertFalse(store.get("proposal:1").collapsed)

    def test_collapse_then_expand_is_idempotent_and_persisted(self) -> None:
        store = ProposalPanelStore()
        store.collapse("proposal:1", at="2026-01-01T00:00:00Z")
        store.collapse("proposal:1", at="2026-01-01T00:05:00Z")  # idempotent
        self.assertTrue(store.get("proposal:1").collapsed)
        round_tripped = ProposalPanelStore.from_json(json.loads(json.dumps(store.to_json())))
        self.assertTrue(round_tripped.get("proposal:1").collapsed)
        round_tripped.expand("proposal:1", at="2026-01-01T01:00:00Z")
        self.assertFalse(round_tripped.get("proposal:1").collapsed)

    def test_panel_cannot_be_dismissed_or_deleted(self) -> None:
        store = ProposalPanelStore()
        for banned in ("dismiss", "delete", "remove", "drop", "purge"):
            self.assertFalse(hasattr(store, banned), f"panel store must not expose {banned!r}")
        self.assertFalse(hasattr(ProposalPanelState, "dismissed"))


class StrategyConsoleReadModelTests(unittest.TestCase):
    def test_partitions_versions_and_offers_apply_for_apply_ready(self) -> None:
        model = StrategyConsoleReadModel(_registry())
        view = model.render(proposal_id="proposal:1")
        self.assertIsNone(view["active"])
        self.assertEqual({v["spec_fingerprint"] for v in view["apply_ready"]}, {"fp-a", "fp-b"})
        self.assertEqual(view["previous"], [])
        self.assertEqual(view["retired"], [])
        self.assertEqual({a["action"] for a in view["actions"]}, {"apply"})
        self.assertFalse(view["proposal_panel"]["collapsed"])

    def test_after_activation_old_active_becomes_a_rollback_target(self) -> None:
        reg = _registry()
        a_id = reg.history()[0].strategy_version_id
        b_id = reg.history()[1].strategy_version_id
        reg.mark_active(a_id, at="2026-01-03T00:00:00Z")
        reg.mark_active(b_id, at="2026-01-04T00:00:00Z")

        view = StrategyConsoleReadModel(reg).render()
        self.assertEqual(view["active"]["spec_fingerprint"], "fp-b")
        self.assertEqual([v["spec_fingerprint"] for v in view["previous"]], ["fp-a"])
        actions = {a["strategy_version_id"]: a["action"] for a in view["actions"]}
        self.assertEqual(actions.get(a_id), "rollback")
        self.assertNotIn(b_id, actions)  # the ACTIVE version has no action

    def test_retired_versions_are_shown_but_never_actionable(self) -> None:
        reg = _registry()
        a_id = reg.history()[0].strategy_version_id
        reg.mark_retired(a_id, at="2026-01-03T00:00:00Z", reason="superseded")
        view = StrategyConsoleReadModel(reg).render()
        self.assertEqual([v["spec_fingerprint"] for v in view["retired"]], ["fp-a"])
        self.assertNotIn(a_id, {a["strategy_version_id"] for a in view["actions"]})

    def test_render_output_is_json_serializable(self) -> None:
        json.dumps(StrategyConsoleReadModel(_registry()).render(proposal_id="proposal:1"))

    def test_panel_state_survives_across_two_render_calls(self) -> None:
        store = ProposalPanelStore()
        model = StrategyConsoleReadModel(_registry(), panel_store=store)
        model.collapse_proposal("proposal:1", at="2026-01-01T00:00:00Z")
        # a fresh read model over the SAME store (a browser reload) still sees it collapsed
        reloaded = StrategyConsoleReadModel(_registry(), panel_store=store)
        self.assertTrue(reloaded.render(proposal_id="proposal:1")["proposal_panel"]["collapsed"])


if __name__ == "__main__":
    unittest.main()
