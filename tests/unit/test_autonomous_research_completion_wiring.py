"""Hotfix #169F: unit tests for the runtime-tick wiring of the
ResearchDirection -> DirectionEvidenceAcquisition -> EvidenceMutationPolicyDecision
-> BoundedHypothesisProposal -> StrategyCandidateRecord chain inside
``AutonomousResearchRuntimeWorker.tick()``.

Reuses fixture transports (never real network) via an injected
``evidence_executor_factory`` - the same dependency-injection point every
other worker collaborator (``brain_factory``, ``now_factory``) already
uses.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace

from gaon.knowledge.content_acquisition import FetchPayload
from gaon.knowledge.external_research_execution import ContentResolutionPayload
from gaon.knowledge.research_mission import MissionStatus, add_candidate, extract_or_update_mission, get_candidate, record_blocked
from gaon.knowledge.strategy_candidate import ALL_STRATEGY_FAMILY_TEMPLATES, StrategyCandidateStatus, new_candidate
from gaon.research.direction_evidence import build_production_executor
from gaon.runtime.autonomous_research_runtime import AutonomousResearchRuntimeWorker, _continuation_request
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationSession
from gaon.runtime.migrations import migrate
from gaon.runtime.telegram_agent import TelegramConversationAgent

NOW = "2026-08-30T00:00:05Z"
SESSION_ID = "telegram:100"

_PASSING_ITEM = {
    "DOI": "10.9999/wiring-test-fixture", "type": "journal-article",
    "title": ["Transaction Cost and Slippage Sensitivity in Systematic Trading"],
    "publisher": "Wiring Test Fixture Press", "container-title": ["Journal of Wiring Test Fixtures"],
    "abstract": "This paper studies transaction cost sensitivity and slippage impact on systematic trading strategy robustness across turnover regimes.",
    "subject": ["finance"], "URL": "https://doi.org/10.9999/wiring-test-fixture",
}


class _CrossrefTransport:
    def get_json(self, url, *, policy):
        return {"message": {"items": [_PASSING_ITEM]}}


class _DoiTransport:
    def resolve(self, url, *, policy):
        return ContentResolutionPayload(final_url="https://arxiv.org/abs/wiring-test-fixture", redirect_chain=(url,))


class _ContentTransport:
    def fetch(self, target, *, policy):
        return FetchPayload(final_url=target.source_locator, content_type="text/plain", content=b"transaction cost slippage sensitivity fixture content")


def _passing_executor_factory():
    # storage_root MUST be an explicit, isolated temp directory - never
    # omit it. build_production_executor()'s own default (storage_root=
    # None) resolves to the REAL production data root (/var/lib/
    # strategylab/gaon-data on Linux CI, D:\Gaon on a local Windows dev
    # machine where it may already exist and silently mask this bug - see
    # Hotfix #171, the prior incident of this exact class). A fresh temp
    # dir per call keeps every tick's executor fully isolated.
    return build_production_executor(
        storage_root=tempfile.mkdtemp(prefix="gaon-169def-wiring-test-"),
        discovery_transport=_CrossrefTransport(), doi_resolution_transport=_DoiTransport(), content_transport=_ContentTransport(),
    )


def _seed_exhausted_mission(connection: sqlite3.Connection, config: GaonRuntimeConfig, session_id: str = SESSION_ID):
    agent = TelegramConversationAgent(config, connection)
    agent._brain._repository.upsert_session(LLMConversationSession(session_id, "test", "telegram", "active", NOW, NOW, {}))
    mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요", existing=None, now=NOW)
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
    default_stagnant_reason = "stagnation: no measurable progress across bounded cycles"
    for sequence, (family, (stage_status, status)) in enumerate(zip((t.family for t in ALL_STRATEGY_FAMILY_TEMPLATES), specs), start=1):
        candidate = new_candidate(family, sequence=sequence, now=NOW)
        if stage_status is None:
            candidate = replace(candidate, status=status, rejected_reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols")
        else:
            candidate = replace(candidate, status=status, rejected_reason=default_stagnant_reason, validation_stage_status=stage_status)
        mission = add_candidate(mission, candidate, now=NOW)
    mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=NOW)
    agent._brain._remember_mission(_continuation_request(session_id, session_id.split(":")[-1], NOW, suffix="seed"), mission)
    return agent


def _config(chat_id: str = "100") -> GaonRuntimeConfig:
    return GaonRuntimeConfig(mode="execute", dry_run=False, telegram_enabled=True, telegram_bot_token="t", telegram_allowed_chat_ids=(chat_id,), approval_signing_secret="s")


class ChainProgressionTests(unittest.TestCase):
    def test_A_full_chain_progresses_direction_to_candidate(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        _seed_exhausted_mission(connection, config)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)
        actions = [worker.tick().action for _ in range(5)]
        self.assertEqual(
            actions,
            ["research_direction_planned", "direction_evidence_acquired", "policy_decision_created", "bounded_hypothesis_created", "candidate_created"],
        )
        connection.close()

    def test_B_one_bounded_action_per_tick(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        _seed_exhausted_mission(connection, config)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)
        # After tick 0 (direction planned), evidence/policy/proposal must
        # NOT all appear in the same tick - each is its own tick.
        worker.tick()
        evidence_before = connection.execute("SELECT COUNT(*) FROM research_direction_evidence").fetchone()[0]
        policy_before = connection.execute("SELECT COUNT(*) FROM research_evidence_mutation_decisions").fetchone()[0]
        self.assertEqual(evidence_before, 0)
        self.assertEqual(policy_before, 0)
        worker.tick()  # direction_evidence_acquired
        evidence_after = connection.execute("SELECT COUNT(*) FROM research_direction_evidence").fetchone()[0]
        policy_after = connection.execute("SELECT COUNT(*) FROM research_evidence_mutation_decisions").fetchone()[0]
        self.assertEqual(evidence_after, 1)
        self.assertEqual(policy_after, 0)  # policy stage has not run yet - proves boundedness
        connection.close()

    def test_C_repeated_ticks_over_unchanged_state_are_idempotent(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        _seed_exhausted_mission(connection, config)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)
        for _ in range(5):
            worker.tick()
        direction_count = connection.execute("SELECT COUNT(*) FROM research_directions").fetchone()[0]
        # tick 5 is the normal cycle_executed fallthrough - the chain itself does not re-run.
        result = worker.tick()
        self.assertEqual(result.action, "cycle_executed")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM research_directions").fetchone()[0], direction_count)
        connection.close()

    def test_D_candidate_rejection_does_not_crash_scheduler(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        agent = _seed_exhausted_mission(connection, config)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)
        for _ in range(5):
            worker.tick()
        mission = agent._brain._mission_for(SESSION_ID)
        candidate = get_candidate(mission, mission.active_candidate_id)
        rejected = replace(candidate, status=StrategyCandidateStatus.REJECTED, rejected_reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols")
        from gaon.knowledge.research_mission import update_candidate

        mission = update_candidate(mission, rejected, now=NOW)
        mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=NOW)
        agent._brain._remember_mission(_continuation_request(SESSION_ID, "100", NOW, suffix="rejected"), mission)
        result = worker.tick()  # must not raise
        self.assertTrue(result.attempted)
        self.assertNotEqual(result.action, "failed")
        connection.close()

    def test_E_provider_missing_does_not_fabricate_progress(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        _seed_exhausted_mission(connection, config)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=lambda: None)
        worker.tick()  # research_direction_planned
        evidence_result = worker.tick()  # direction_evidence_acquired (executor=None -> honest PROVIDER_NOT_CONFIGURED)
        self.assertEqual(evidence_result.action, "direction_evidence_acquired")
        policy_result = worker.tick()
        self.assertEqual(policy_result.action, "policy_decision_created")
        self.assertEqual(policy_result.policy_status, "blocked_insufficient_evidence")
        exhaustion_result = worker.tick()
        self.assertEqual(exhaustion_result.action, "hypothesis_value_space_exhausted")
        # No proposal/candidate was ever fabricated.
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM research_hypothesis_proposals").fetchone()[0], 0)
        connection.close()

    def test_F_exhausted_bounded_values_stops_honestly(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        _seed_exhausted_mission(connection, config)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=lambda: None)
        for _ in range(4):
            worker.tick()
        result = worker.tick()
        self.assertEqual(result.action, "hypothesis_value_space_exhausted")
        # A repeated tick against the same exhausted state stays exhausted - never crashes, never fabricates a proposal/candidate.
        result_again = worker.tick()
        self.assertEqual(result_again.action, "hypothesis_value_space_exhausted")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM research_hypothesis_proposals").fetchone()[0], 0)
        connection.close()

    def test_G_ready_for_approval_stops_autonomous_progression(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        agent = _seed_exhausted_mission(connection, config)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)
        for _ in range(5):
            worker.tick()
        mission = agent._brain._mission_for(SESSION_ID)
        candidate = get_candidate(mission, mission.active_candidate_id)
        from gaon.knowledge.research_mission import record_promotion_candidate

        for index in range(3):
            mission = record_promotion_candidate(
                mission, strategy_fingerprint=candidate.strategy_fingerprint if index == 0 else f"other-{index}",
                candidate_id=candidate.candidate_id if index == 0 else f"KR-ST-90{index}", now=NOW,
            )
        self.assertEqual(mission.status, MissionStatus.AWAITING_HUMAN_APPROVAL)
        agent._brain._remember_mission(_continuation_request(SESSION_ID, "100", NOW, suffix="approval"), mission)
        result = worker.tick()
        self.assertEqual(result.action, "skipped_awaiting_human_or_terminal")
        self.assertTrue(result.approval_required)
        self.assertFalse(result.autonomous_progression)
        connection.close()

    def test_H_approved_mission_is_not_automatically_applied(self) -> None:
        # APPROVED/AWAITING_HUMAN_APPROVAL is not APPLIED/ACTIVE - the
        # worker has zero code path that ever writes to any
        # strategy_deployment_*/strategy_execution_*/champion_* table.
        import inspect

        import gaon.runtime.autonomous_research_runtime as module

        source = inspect.getsource(module)
        for forbidden in ("gaon.adapters.trading", "gaon.adapters.strategy_execution", "gaon.adapters.strategy_deployment", "gaon.knowledge.promotion_gate", "gaon.knowledge.human_gated_promotion"):
            self.assertNotIn(f"import {forbidden}", source)
            self.assertNotIn(f"from {forbidden}", source)

    def test_I_completed_mission_stops(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        agent = TelegramConversationAgent(config, connection)
        agent._brain._repository.upsert_session(LLMConversationSession(SESSION_ID, "test", "telegram", "active", NOW, NOW, {}))
        mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요", existing=None, now=NOW)
        mission = replace(mission, status=MissionStatus.COMPLETED, updated_at=NOW)
        agent._brain._remember_mission(_continuation_request(SESSION_ID, "100", NOW, suffix="completed"), mission)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)
        result = worker.tick()
        self.assertEqual(result.action, "skipped_awaiting_human_or_terminal")
        connection.close()

    def test_J_cancelled_mission_stops(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        agent = TelegramConversationAgent(config, connection)
        agent._brain._repository.upsert_session(LLMConversationSession(SESSION_ID, "test", "telegram", "active", NOW, NOW, {}))
        mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요", existing=None, now=NOW)
        mission = replace(mission, status=MissionStatus.CANCELLED, updated_at=NOW)
        agent._brain._remember_mission(_continuation_request(SESSION_ID, "100", NOW, suffix="cancelled"), mission)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)
        result = worker.tick()
        self.assertEqual(result.action, "skipped_awaiting_human_or_terminal")
        connection.close()

    def test_K_live_order_count_remains_zero(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        _seed_exhausted_mission(connection, config)
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)
        for _ in range(6):
            worker.tick()
        non_read_only = connection.execute("SELECT COUNT(*) FROM llm_tool_audit WHERE risk_level != 'read_only'").fetchone()[0]
        self.assertEqual(non_read_only, 0)
        connection.close()

    def test_L_production_strategy_tables_unchanged(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        config = _config()
        _seed_exhausted_mission(connection, config)
        before = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("strategy_deployment_requests", "strategy_execution_plans", "strategy_execution_runs", "champion_registry")
        }
        worker = AutonomousResearchRuntimeWorker(config, connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)
        for _ in range(6):
            worker.tick()
        after = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("strategy_deployment_requests", "strategy_execution_plans", "strategy_execution_runs", "champion_registry")
        }
        self.assertEqual(before, after)
        connection.close()


if __name__ == "__main__":
    unittest.main()
