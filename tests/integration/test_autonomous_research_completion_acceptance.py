"""Hotfix #169D-F acceptance test: the complete autonomous research chain,
exercised end to end through the real ``AutonomousResearchRuntimeWorker``
entrypoint, plus the existing Web read endpoints Gaon's approval workflow
already relies on.

Core acceptance criteria this proves:
- ResearchMission BLOCKED/exhausted -> FailureAnalysis -> ResearchDirection
  -> DirectionEvidenceAcquisition -> EvidenceMutationPolicyDecision ->
  BoundedHypothesisProposal -> StrategyCandidateRecord, one bounded action
  per tick, fully idempotent;
- reaching the mission's EXISTING MissionStatus.AWAITING_HUMAN_APPROVAL gate
  (via the EXISTING record_promotion_candidate - never a new mechanism) is
  a hard stop for the autonomous worker;
- the new candidate is visible through the EXISTING Web
  _handle_candidates_list/_handle_mission_status read endpoints - no second
  approval subsystem was introduced;
- no candidate/strategy/backtest/order/Champion/approval-bypass/production-
  apply authority is ever reachable.
"""

from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace

from gaon.knowledge.content_acquisition import FetchPayload
from gaon.knowledge.external_research_execution import ContentResolutionPayload
from gaon.knowledge.research_mission import (
    MissionStatus,
    add_candidate,
    candidate_records,
    extract_or_update_mission,
    get_candidate,
    record_blocked,
    record_promotion_candidate,
)
from gaon.knowledge.strategy_candidate import ALL_STRATEGY_FAMILY_TEMPLATES, StrategyCandidateStatus, new_candidate
from gaon.research.direction_evidence import build_production_executor
from gaon.runtime.autonomous_research_runtime import AutonomousResearchRuntimeWorker, _continuation_request
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationRequest, LLMConversationSession
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter, _handle_candidates_list, _handle_mission_status

NOW = "2026-08-30T00:00:05Z"
SESSION_ID = "telegram:100"

_PASSING_ITEM = {
    "DOI": "10.9999/acceptance-169def-fixture", "type": "journal-article",
    "title": ["Transaction Cost and Slippage Sensitivity in Systematic Trading"],
    "publisher": "Acceptance Fixture Press", "container-title": ["Journal of Acceptance Fixtures"],
    "abstract": "This paper studies transaction cost sensitivity and slippage impact on systematic trading strategy robustness across turnover regimes.",
    "subject": ["finance"], "URL": "https://doi.org/10.9999/acceptance-169def-fixture",
}


class _CrossrefTransport:
    def get_json(self, url, *, policy):
        return {"message": {"items": [_PASSING_ITEM]}}


class _DoiTransport:
    def resolve(self, url, *, policy):
        return ContentResolutionPayload(final_url="https://arxiv.org/abs/acceptance-169def-fixture", redirect_chain=(url,))


class _ContentTransport:
    def fetch(self, target, *, policy):
        return FetchPayload(final_url=target.source_locator, content_type="text/plain", content=b"transaction cost slippage sensitivity fixture content")


def _passing_executor_factory():
    return build_production_executor(discovery_transport=_CrossrefTransport(), doi_resolution_transport=_DoiTransport(), content_transport=_ContentTransport())


def _config() -> GaonRuntimeConfig:
    return GaonRuntimeConfig(mode="execute", dry_run=False, telegram_enabled=True, telegram_bot_token="synthetic-token", telegram_allowed_chat_ids=("100",), approval_signing_secret="synthetic-approval-secret")


class AutonomousResearchCompletionAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.config = _config()
        self.agent = TelegramConversationAgent(self.config, self.connection)
        self.agent._brain._repository.upsert_session(LLMConversationSession(SESSION_ID, "test", "telegram", "active", NOW, NOW, {}))

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
        self.agent._brain._remember_mission(_continuation_request(SESSION_ID, "100", NOW, suffix="seed"), mission)
        self.worker = AutonomousResearchRuntimeWorker(self.config, self.connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)

    def tearDown(self) -> None:
        self.connection.close()

    def test_full_chain_reaches_candidate_then_stops_at_human_approval(self) -> None:
        actions = [self.worker.tick().action for _ in range(5)]
        self.assertEqual(
            actions,
            ["research_direction_planned", "direction_evidence_acquired", "policy_decision_created", "bounded_hypothesis_created", "candidate_created"],
        )

        mission = self.agent._brain._mission_for(SESSION_ID)
        candidate = get_candidate(mission, mission.active_candidate_id)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.status, StrategyCandidateStatus.EXPLORING)
        self.assertEqual(mission.status, MissionStatus.ACTIVE)

        # No production/backtest/order/approval side effect anywhere.
        for table in ("strategy_deployment_requests", "strategy_execution_plans", "champion_registry", "approvals", "promotion_requests"):
            self.assertEqual(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

        # Reuse the EXISTING promotion-candidate mechanism to reach the
        # EXISTING AWAITING_HUMAN_APPROVAL gate - never invented here.
        approval_mission = mission
        for index in range(3):
            approval_mission = record_promotion_candidate(
                approval_mission,
                strategy_fingerprint=candidate.strategy_fingerprint if index == 0 else f"acceptance-other-{index}",
                candidate_id=candidate.candidate_id if index == 0 else f"KR-ST-90{index}",
                now=NOW,
            )
        self.assertEqual(approval_mission.status, MissionStatus.AWAITING_HUMAN_APPROVAL)
        self.agent._brain._remember_mission(_continuation_request(SESSION_ID, "100", NOW, suffix="approval"), approval_mission)

        stop_result = self.worker.tick()
        self.assertEqual(stop_result.action, "skipped_awaiting_human_or_terminal")
        self.assertTrue(stop_result.approval_required)
        self.assertFalse(stop_result.autonomous_progression)

        # A second stop tick is idempotent - no duplicate approval state.
        lineage_before = self.connection.execute("SELECT COUNT(*) FROM research_hypothesis_execution_lineage").fetchone()[0]
        self.worker.tick()
        lineage_after = self.connection.execute("SELECT COUNT(*) FROM research_hypothesis_execution_lineage").fetchone()[0]
        self.assertEqual(lineage_before, lineage_after)

        # Visible through the EXISTING Web read endpoints - no second
        # approval subsystem. Mirrored into an actual Web-scoped session,
        # exactly the storage shape a real Web-originated conversation
        # already uses (GaonWebChatAdapter.mission_for reads
        # "web:{session_ref}" - a separate namespace from the autonomous
        # worker's own "telegram:{chat_id}" session by existing design).
        web_adapter = GaonWebChatAdapter(self.config, self.connection)
        web_session_ref = "acceptance-web-view"
        web_adapter._brain._repository.upsert_session(LLMConversationSession(f"web:{web_session_ref}", "test", "web", "active", NOW, NOW, {}))
        web_adapter._brain._remember_mission(
            LLMConversationRequest(session_id=f"web:{web_session_ref}", user_ref="test", source="web", text="x", received_at=NOW, message_id="web:acceptance:1"),
            approval_mission,
        )
        candidates_status, candidates_payload = _handle_candidates_list(web_adapter, {"session_ref": [web_session_ref]})
        mission_status_code, mission_payload = _handle_mission_status(web_adapter, {"session_ref": [web_session_ref]})
        self.assertEqual(candidates_status, 200)
        self.assertEqual(mission_status_code, 200)
        self.assertEqual(mission_payload["status"], "awaiting_human_approval")
        matching = [item for item in candidates_payload["candidates"] if item["candidate_id"] == candidate.candidate_id]
        self.assertEqual(len(matching), 1)
        self.assertIn("hypothesis_summary", matching[0])
        self.assertIn("breakout_lookback", matching[0]["hypothesis_summary"])

    def test_schema_version_is_42(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 42)


if __name__ == "__main__":
    unittest.main()
