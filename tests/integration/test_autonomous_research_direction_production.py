"""Hotfix #168 acceptance: evidence-backed research-direction planning once
the bounded strategy-hypothesis space is genuinely exhausted with no
narrow-recovery-eligible candidate.

Proves the new stage added to ``AutonomousResearchRuntimeWorker.tick()``:
EXHAUSTED -> FAILURE ANALYSIS -> RESEARCH PRIORITY -> RESEARCH DIRECTION,
reachable only from ``blocked_no_recovery`` on
``strategy_hypothesis_space_exhausted`` - never from any other blocked
reason, never advancing past AWAITING_HUMAN_APPROVAL, never mutating
strategy config/orders/champion/approval state, and never polluting human
conversation history or Cognitive Core feedback (system-turn isolation).
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import (
    MissionStatus,
    add_candidate,
    extract_or_update_mission,
    record_blocked,
    record_promotion_candidate,
)
from gaon.knowledge.strategy_candidate import (
    STRATEGY_FAMILY_TEMPLATES,
    STRATEGY_SPACE_EXPANSION_TEMPLATES,
    StrategyCandidateStatus,
    new_candidate,
)
from gaon.research.research_direction import ResearchDirectionRepository
from gaon.runtime.autonomous_research_runtime import (
    AutonomousResearchRuntimeService,
    AutonomousResearchRuntimeWorker,
)
from gaon.runtime.scheduled_automation import ScheduledJobRepository
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

from test_strategy_centric_autonomous_research import _config, _RecordingTelegramClient, _update

_NOW = "2026-08-29T00:00:05Z"

def _all_nine_families_exhausted() -> tuple[tuple[str, str, StrategyCandidateStatus], ...]:
    """Every one of the bounded 9-family declarative grammar's families,
    each already tried and terminal - the only real way
    ``strategy_hypothesis_space_exhausted`` can fire (see
    ``next_untried_family``/``expand_strategy_space_candidate``). Cycles
    through a few different rejection reasons so the failure-analysis
    breakdown this test exercises is not degenerate/single-class."""
    reasons = (
        ("economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols", StrategyCandidateStatus.REJECTED),
        ("sample_pool_exhausted_no_untried_robustness_symbol", StrategyCandidateStatus.STAGNANT),
    )
    all_templates = (*STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_TEMPLATES)
    return tuple(
        (template.family, *reasons[index % len(reasons)])
        for index, template in enumerate(all_templates)
    )


_EXHAUSTED_FAMILIES = _all_nine_families_exhausted()


def _fake_request(session_id: str = "telegram:100"):
    from gaon.runtime.llm_conversation import LLMConversationRequest

    return LLMConversationRequest(session_id=session_id, user_ref="test", source="telegram", text="test", received_at=_NOW)


class _DirectionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()
        # A real prior turn creates the durable conversation_sessions row
        # _remember_mission needs - exactly like a live Telegram user would.
        process_update(parse_update_result(_update(1, 1, "안녕하세요"), received_at=_NOW), self.runtime, self.client)

    def _mission(self):
        return self.agent._brain._mission_for("telegram:100")

    def _seed_exhausted_mission(self) -> None:
        mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요", existing=None, now=_NOW
        )
        for sequence, (family, reason, status) in enumerate(_EXHAUSTED_FAMILIES, start=1):
            candidate = new_candidate(family, sequence=sequence, now=_NOW)
            candidate = replace(candidate, status=status, rejected_reason=reason)
            mission = add_candidate(mission, candidate, now=_NOW)
        mission = record_blocked(
            mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=_NOW
        )
        self.agent._brain._remember_mission(_fake_request(), mission)

    def _conversation_message_count(self) -> int:
        return len(self.store.conversations.list_messages("telegram:100", limit=1000))

    def _cognitive_record_count(self) -> int:
        return self.store._connection.execute("SELECT COUNT(*) FROM cognitive_records").fetchone()[0]

    def _observed_table_counts(self) -> dict[str, int]:
        tables = (
            "champion_registry", "champion_history", "promotion_requests", "promotion_decisions",
            "approvals", "research_approval_decisions", "research_config_approvals",
            "strategy_deployment_requests", "strategy_deployment_runs",
            "strategy_execution_plans", "strategy_execution_runs",
        )
        return {table: self.store._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


class ExhaustedSpaceMovesToDirectionPlanningTests(_DirectionTestCase):
    def test_A_exhausted_space_with_no_recoverable_candidate_moves_to_direction_planning(self) -> None:
        self._seed_exhausted_mission()
        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: _NOW)

        result = worker.tick()

        self.assertNotEqual(result.action, "blocked_no_recovery")
        self.assertEqual(result.action, "research_direction_planned")
        self.assertIsNotNone(result.direction_id)
        self.assertIsNotNone(result.failure_class)
        self.assertEqual(result.next_research_action, "wait_for_required_data")
        self.assertEqual(result.direction_status, "awaiting_evidence")
        repository = ResearchDirectionRepository(self.store._connection)
        self.assertEqual(repository.count_directions_for_session("telegram:100"), 1)

    def test_B_repeated_tick_on_unchanged_state_never_duplicates_the_direction(self) -> None:
        self._seed_exhausted_mission()
        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: _NOW)

        first = worker.tick()
        second = worker.tick()
        third = worker.tick()

        self.assertEqual(first.action, "research_direction_planned")
        self.assertIn(second.action, {"research_direction_awaiting_evidence", "research_direction_active"})
        self.assertEqual(second.action, third.action)
        self.assertEqual(first.direction_id, second.direction_id)
        repository = ResearchDirectionRepository(self.store._connection)
        self.assertEqual(repository.count_directions_for_session("telegram:100"), 1)

    def test_C_bounded_budget_stays_honestly_waiting_across_many_ticks(self) -> None:
        self._seed_exhausted_mission()
        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: _NOW)

        results = [worker.tick() for _ in range(10)]

        # Never crashes, never fabricates a different action out of thin
        # air, never grows unboundedly - always resolves to the same
        # idempotent, honest "still waiting for evidence" read.
        self.assertTrue(all(r.action in {"research_direction_planned", "research_direction_awaiting_evidence"} for r in results))
        self.assertEqual(results[-1].direction_status, "awaiting_evidence")
        repository = ResearchDirectionRepository(self.store._connection)
        self.assertEqual(repository.count_directions_for_session("telegram:100"), 1)

    def test_D_provider_unavailable_is_never_diverted_into_direction_planning(self) -> None:
        mission = extract_or_update_mission(
            "국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요", existing=None, now=_NOW
        )
        mission = record_blocked(mission, reason="provider_unavailable: no data source responded", now=_NOW)
        self.agent._brain._remember_mission(_fake_request(), mission)

        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: _NOW)
        result = worker.tick()

        self.assertEqual(result.action, "blocked_no_recovery")
        self.assertEqual(result.blocker, "provider_unavailable: no data source responded")
        self.assertIsNone(result.direction_id)
        repository = ResearchDirectionRepository(self.store._connection)
        self.assertEqual(repository.count_directions_for_session("telegram:100"), 0)

    def test_E_awaiting_human_approval_stops_even_with_direction_history(self) -> None:
        self._seed_exhausted_mission()
        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: _NOW)
        worker.tick()  # produces a direction record first

        mission = self._mission()
        for index in range(3):
            mission = record_promotion_candidate(mission, strategy_fingerprint=f"verified-{index}", candidate_id=f"KR-ST-90{index}", now=_NOW)
        self.agent._brain._remember_mission(_fake_request(), mission)
        self.assertEqual(mission.status, MissionStatus.AWAITING_HUMAN_APPROVAL)

        result = worker.tick()

        self.assertEqual(result.action, "skipped_awaiting_human_or_terminal")
        self.assertIsNone(result.direction_id)

    def test_F_direction_planning_never_mutates_strategy_order_champion_or_approval_state(self) -> None:
        self._seed_exhausted_mission()
        counts_before = self._observed_table_counts()

        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: _NOW)
        worker.tick()
        worker.tick()

        counts_after = self._observed_table_counts()
        self.assertEqual(counts_before, counts_after)

    def test_G_direction_planning_tick_is_a_synthetic_system_turn_never_polluting_conversation_or_cognitive_state(self) -> None:
        self._seed_exhausted_mission()
        messages_before = self._conversation_message_count()
        cognitive_before = self._cognitive_record_count()

        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: _NOW)
        worker.tick()

        self.assertEqual(self._conversation_message_count(), messages_before)
        self.assertEqual(self._cognitive_record_count(), cognitive_before)

    def test_H_sustainability_dimensions_are_read_only_context_never_risk_or_leverage_actions(self) -> None:
        self._seed_exhausted_mission()
        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: _NOW)
        result = worker.tick()

        repository = ResearchDirectionRepository(self.store._connection)
        fingerprint = result.direction_id.split(":", 1)[1]
        direction = repository.find_direction_by_fingerprint(fingerprint)
        self.assertIsNotNone(direction)
        self.assertIn("sustainability_dimensions_considered", direction.priority)
        self.assertTrue(len(direction.priority["sustainability_dimensions_considered"]) > 0)
        for forbidden in ("risk_increase", "leverage_increase", "validation_threshold_relaxation", "live_order_execution"):
            self.assertIn(forbidden, direction.prohibited_actions)
        self.assertNotIn("increase_leverage", direction.allowed_research_scope)
        self.assertNotIn("increase_risk", direction.allowed_research_scope)

    def test_I_scheduler_result_json_honestly_reports_direction_fields(self) -> None:
        self._seed_exhausted_mission()
        repository = ScheduledJobRepository(self.store._connection)
        service = AutonomousResearchRuntimeService(_config(), repository, now_factory=lambda: _NOW)

        service.tick()

        run_row = self.store._connection.execute(
            "SELECT result_json FROM scheduled_automation_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(run_row)
        import json

        payload = json.loads(run_row[0])
        self.assertEqual(payload["action"], "research_direction_planned")
        self.assertTrue(payload["direction_id"])
        self.assertEqual(payload["direction_status"], "awaiting_evidence")
        self.assertEqual(payload["next_research_action"], "wait_for_required_data")
        self.assertTrue(payload["failure_class"])


if __name__ == "__main__":
    unittest.main()
