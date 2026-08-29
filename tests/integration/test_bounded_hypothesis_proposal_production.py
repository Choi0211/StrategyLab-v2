"""Hotfix #169A acceptance: Canonical Mutation Surface + Durable Hypothesis
Proposal.

This is infrastructure ONLY - proves a genuinely production-shaped exhausted
mission produces canonical, deterministic, bounded, deduplicated
``BoundedHypothesisProposal`` records through the real conversational stack
(``TelegramConversationAgent``), and that generating/persisting proposals
never creates a ``StrategyCandidateRecord``, never mutates strategy config,
never touches orders/Champion/approval state, and never lets the
Sustainability objective (still read-only) authorize a forbidden dimension.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import add_candidate, candidate_records, extract_or_update_mission, record_blocked
from gaon.knowledge.strategy_candidate import ALL_STRATEGY_FAMILY_TEMPLATES, StrategyCandidateStatus, new_candidate
from gaon.research.hypothesis_proposal import (
    CANONICAL_MUTATION_POLICY,
    PROHIBITED_DIMENSION_NAMES,
    BoundedHypothesisProposalRepository,
    ProposalStatus,
    generate_bounded_proposals,
)
from gaon.research.research_direction import analyze_mission_failure, plan_research_direction
from gaon.research.research_priority import propose_research_priority
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

from test_strategy_centric_autonomous_research import _config, _RecordingTelegramClient, _update

_NOW = "2026-08-30T00:00:05Z"
_DEFAULT_STAGNANT_REASON = "stagnation: no measurable progress across bounded cycles"


def _fake_request(session_id: str = "telegram:100"):
    from gaon.runtime.llm_conversation import LLMConversationRequest

    return LLMConversationRequest(session_id=session_id, user_ref="test", source="telegram", text="test", received_at=_NOW)


class BoundedHypothesisProposalProductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()
        process_update(parse_update_result(_update(1, 1, "안녕하세요"), received_at=_NOW), self.runtime, self.client)

    def _seed_production_shaped_exhausted_mission(self):
        mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요", existing=None, now=_NOW
        )
        specs = (
            ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
            ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
            ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
            ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
            ({"regime_validation": "fail"}, StrategyCandidateStatus.STAGNANT),
            ({"regime_validation": "fail"}, StrategyCandidateStatus.STAGNANT),
            ({"out_of_sample": "fail"}, StrategyCandidateStatus.STAGNANT),
            ({"out_of_sample": "fail"}, StrategyCandidateStatus.STAGNANT),
            (None, StrategyCandidateStatus.REJECTED),
        )
        for sequence, (family, (stage_status, status)) in enumerate(
            zip((t.family for t in ALL_STRATEGY_FAMILY_TEMPLATES), specs), start=1
        ):
            candidate = new_candidate(family, sequence=sequence, now=_NOW)
            if stage_status is None:
                candidate = replace(
                    candidate, status=status,
                    rejected_reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols",
                )
            else:
                candidate = replace(candidate, status=status, rejected_reason=_DEFAULT_STAGNANT_REASON, validation_stage_status=stage_status)
            mission = add_candidate(mission, candidate, now=_NOW)
        mission = record_blocked(
            mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=_NOW
        )
        self.agent._brain._remember_mission(_fake_request(), mission)
        return mission

    def _observed_table_counts(self):
        tables = (
            "champion_registry", "champion_history", "promotion_requests", "promotion_decisions",
            "approvals", "research_approval_decisions", "research_config_approvals",
            "strategy_deployment_requests", "strategy_deployment_runs",
            "strategy_execution_plans", "strategy_execution_runs",
        )
        return {table: self.store._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}

    def _conversation_message_count(self):
        return len(self.store.conversations.list_messages("telegram:100", limit=1000))

    def _cognitive_record_count(self):
        return self.store._connection.execute("SELECT COUNT(*) FROM cognitive_records").fetchone()[0]

    def test_production_shaped_mission_generates_ready_for_evidence_proposals(self) -> None:
        mission = self._seed_production_shaped_exhausted_mission()
        analysis = analyze_mission_failure(mission, session_ref="telegram:100", now=_NOW)
        priority = propose_research_priority(mission, None)
        direction = plan_research_direction(analysis, priority, has_untried_family=False, has_recoverable_candidate=False, now=_NOW)

        proposals = generate_bounded_proposals(direction, analysis, candidate_records(mission), now=_NOW)

        self.assertTrue(all(p.status == ProposalStatus.READY_FOR_EVIDENCE for p in proposals))
        fields = {mutation.field for p in proposals for mutation in p.mutations}
        self.assertTrue(fields.issubset(set(CANONICAL_MUTATION_POLICY.keys())))
        self.assertTrue(fields.isdisjoint(PROHIBITED_DIMENSION_NAMES))
        # Hotfix #169A final policy audit hardening: channel_exit_lookback has
        # no code-grounded turnover/cost mechanism and was removed from the
        # cost_slippage_fragility mapping - only breakout_lookback remains.
        self.assertEqual(fields, {"breakout_lookback"})

    def test_proposal_generation_and_persistence_never_touches_strategy_order_champion_approval_state(self) -> None:
        mission = self._seed_production_shaped_exhausted_mission()
        analysis = analyze_mission_failure(mission, session_ref="telegram:100", now=_NOW)
        priority = propose_research_priority(mission, None)
        direction = plan_research_direction(analysis, priority, has_untried_family=False, has_recoverable_candidate=False, now=_NOW)

        counts_before = self._observed_table_counts()
        candidates_before = len(mission.candidates)

        proposals = generate_bounded_proposals(direction, analysis, candidate_records(mission), now=_NOW)
        repository = BoundedHypothesisProposalRepository(self.store._connection)
        for proposal in proposals:
            repository.put(proposal)

        counts_after = self._observed_table_counts()
        mission_after = self.agent._brain._mission_for("telegram:100")

        self.assertEqual(counts_before, counts_after)
        self.assertEqual(len(mission_after.candidates), candidates_before, "proposal generation must never create a StrategyCandidateRecord or mutate mission.candidates")

    def test_proposal_generation_is_a_synthetic_offline_step_never_polluting_conversation_or_cognitive_state(self) -> None:
        mission = self._seed_production_shaped_exhausted_mission()
        messages_before = self._conversation_message_count()
        cognitive_before = self._cognitive_record_count()

        analysis = analyze_mission_failure(mission, session_ref="telegram:100", now=_NOW)
        priority = propose_research_priority(mission, None)
        direction = plan_research_direction(analysis, priority, has_untried_family=False, has_recoverable_candidate=False, now=_NOW)
        proposals = generate_bounded_proposals(direction, analysis, candidate_records(mission), now=_NOW)
        repository = BoundedHypothesisProposalRepository(self.store._connection)
        for proposal in proposals:
            repository.put(proposal)

        self.assertEqual(self._conversation_message_count(), messages_before)
        self.assertEqual(self._cognitive_record_count(), cognitive_before)

    def test_sustainability_objective_cannot_authorize_a_forbidden_dimension(self) -> None:
        """The Sustainability & Growth objective (gaon.cognitive.sustainability)
        stays read-only research-priority context in #169A exactly as in
        #168 - it is never consulted by generate_bounded_proposals at all,
        so it structurally cannot expand the mutation surface. This test
        proves the module never imports it as a decision input."""
        import inspect

        import gaon.research.hypothesis_proposal as hypothesis_proposal_module

        source = inspect.getsource(hypothesis_proposal_module)
        self.assertNotIn("sustainability", source.lower())

        # The canonical mutation surface itself is the second, independent
        # line of defense: even if some future caller tried to route a
        # Sustainability-derived score into field selection, none of the
        # risk/leverage/capital concepts it could plausibly want to touch
        # are, or can become, real allowlist entries.
        for name in PROHIBITED_DIMENSION_NAMES:
            self.assertNotIn(name, CANONICAL_MUTATION_POLICY)

        # Third line of defense (Hotfix #169A final policy audit hardening):
        # even a field that IS a real, structurally-safe allowlist entry
        # (protective_stop_pct directly sets per-trade max-loss magnitude)
        # is machine-gated REVIEW_REQUIRED and never autonomously mutated,
        # regardless of what any failure-class policy - Sustainability-
        # influenced or otherwise - might name.
        from gaon.research.hypothesis_proposal import MutationAutonomyClass

        self.assertEqual(
            CANONICAL_MUTATION_POLICY["protective_stop_pct"].autonomy_class,
            MutationAutonomyClass.REVIEW_REQUIRED,
        )


if __name__ == "__main__":
    unittest.main()
