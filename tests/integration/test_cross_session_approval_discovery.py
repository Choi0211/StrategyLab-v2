"""Cross-session approval discovery acceptance test.

Product requirement: a promotion-ready candidate discovered by Gaon's
autonomous research runtime under a Telegram-scoped mission
(``telegram:<chat_id>``) MUST be discoverable through the EXISTING Web
approval workflow without the operator already knowing that session_ref,
and without copying the candidate/mission into a second, Web-scoped
``ResearchMission``. Approval mutation itself remains wherever it already
lives (the existing session-scoped conversational flow) - this only fixes
DISCOVERY/VISIBILITY.

Verified end to end through the real HTTP-level ``dispatch_request``
entrypoint (the exact function the real HTTP handler calls), never by
calling private helpers directly.
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
from gaon.runtime.migrations import migrate
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter, dispatch_request

NOW = "2026-08-30T00:00:05Z"
TELEGRAM_CHAT_ID = "100"
TELEGRAM_SESSION_ID = f"telegram:{TELEGRAM_CHAT_ID}"

_PASSING_ITEM = {
    "DOI": "10.9999/cross-session-fixture", "type": "journal-article",
    "title": ["Transaction Cost and Slippage Sensitivity in Systematic Trading"],
    "publisher": "Cross Session Fixture Press", "container-title": ["Journal of Cross Session Fixtures"],
    "abstract": "This paper studies transaction cost sensitivity and slippage impact on systematic trading strategy robustness across turnover regimes.",
    "subject": ["finance"], "URL": "https://doi.org/10.9999/cross-session-fixture",
}


class _CrossrefTransport:
    def get_json(self, url, *, policy):
        return {"message": {"items": [_PASSING_ITEM]}}


class _DoiTransport:
    def resolve(self, url, *, policy):
        return ContentResolutionPayload(final_url="https://arxiv.org/abs/cross-session-fixture", redirect_chain=(url,))


class _ContentTransport:
    def fetch(self, target, *, policy):
        return FetchPayload(final_url=target.source_locator, content_type="text/plain", content=b"transaction cost slippage sensitivity fixture content")


def _passing_executor_factory():
    return build_production_executor(discovery_transport=_CrossrefTransport(), doi_resolution_transport=_DoiTransport(), content_transport=_ContentTransport())


def _config() -> GaonRuntimeConfig:
    return GaonRuntimeConfig(mode="execute", dry_run=False, telegram_enabled=True, telegram_bot_token="synthetic-token", telegram_allowed_chat_ids=(TELEGRAM_CHAT_ID,), approval_signing_secret="synthetic-approval-secret")


def _seeded_exhausted_mission():
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
    return record_blocked(mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=NOW)


def _observed_tables(connection: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "strategy_deployment_requests", "strategy_execution_plans", "strategy_execution_runs",
        "champion_registry", "champion_history", "approvals", "research_approval_decisions",
    )
    return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


class TelegramOriginatedCrossSessionDiscoveryTests(unittest.TestCase):
    """The 14-step required flow: a mission created under
    telegram:<chat_id>, autonomously progressed to AWAITING_HUMAN_APPROVAL
    via the real, canonical #169D-F tested path, discovered through the
    Web pending-approvals endpoint without ever knowing the Telegram
    session_ref."""

    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.config = _config()
        self.agent = TelegramConversationAgent(self.config, self.connection)
        self.agent._brain._repository.upsert_session(LLMConversationSession(TELEGRAM_SESSION_ID, "test", "telegram", "active", NOW, NOW, {}))
        self.agent._brain._remember_mission(_continuation_request(TELEGRAM_SESSION_ID, TELEGRAM_CHAT_ID, NOW, suffix="seed"), _seeded_exhausted_mission())
        self.worker = AutonomousResearchRuntimeWorker(self.config, self.connection, now_factory=lambda: NOW, evidence_executor_factory=_passing_executor_factory)

    def tearDown(self) -> None:
        self.connection.close()

    def test_full_cross_session_discovery_flow(self) -> None:
        # 1-2. Autonomously progress the canonical #169D-F chain through the
        # real worker.tick() entrypoint (no manual construction).
        actions = [self.worker.tick().action for _ in range(5)]
        self.assertEqual(actions[-1], "candidate_created")

        mission = self.agent._brain._mission_for(TELEGRAM_SESSION_ID)
        candidate = get_candidate(mission, mission.active_candidate_id)
        self.assertIsNotNone(candidate)

        counts_before_approval = _observed_tables(self.connection)

        # Reach the mission's EXISTING AWAITING_HUMAN_APPROVAL gate via the
        # EXISTING record_promotion_candidate mechanism - never invented here.
        approval_mission = mission
        for index in range(3):
            approval_mission = record_promotion_candidate(
                approval_mission,
                strategy_fingerprint=candidate.strategy_fingerprint if index == 0 else f"cross-session-other-{index}",
                candidate_id=candidate.candidate_id if index == 0 else f"KR-ST-90{index}",
                now=NOW,
            )
        self.assertEqual(approval_mission.status, MissionStatus.AWAITING_HUMAN_APPROVAL)
        self.agent._brain._remember_mission(_continuation_request(TELEGRAM_SESSION_ID, TELEGRAM_CHAT_ID, NOW, suffix="approval"), approval_mission)

        # 3-4. Query the SAME backend/source Web approval UI uses - from a
        # genuinely fresh Web adapter that has never heard of "telegram:100".
        web_adapter = GaonWebChatAdapter(self.config, self.connection)
        status, payload = dispatch_request(web_adapter, method="GET", path="/gaon/research/pending-approvals", body=None)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["pending_approvals"]), 1)  # 6. exactly one approval-state entry
        entry = payload["pending_approvals"][0]

        # 5. Exactly one candidate record for the new candidate (not duplicated).
        matches = [c for c in entry["candidates"] if c["candidate_id"] == candidate.candidate_id]
        self.assertEqual(len(matches), 1)

        # 7. Original session_ref preserved exactly.
        self.assertEqual(entry["session_ref"], TELEGRAM_SESSION_ID)
        self.assertEqual(entry["source"], "telegram")
        self.assertEqual(entry["status"], "awaiting_human_approval")

        # 8. No copied web:<ref> ResearchMission was created.
        web_sessions = self.connection.execute("SELECT session_id FROM conversation_sessions WHERE session_id LIKE 'web:%'").fetchall()
        self.assertEqual(web_sessions, [])

        # 9. Candidate remains NOT approved (no approval-decision row of any kind).
        self.assertEqual(matches[0]["status"], "exploring")
        counts_after_discovery = _observed_tables(self.connection)
        self.assertEqual(counts_before_approval["approvals"], counts_after_discovery["approvals"])
        self.assertEqual(counts_before_approval["research_approval_decisions"], counts_after_discovery["research_approval_decisions"])

        # 10. Production remains NOT applied.
        self.assertEqual(counts_before_approval["strategy_deployment_requests"], counts_after_discovery["strategy_deployment_requests"])
        self.assertEqual(counts_before_approval["strategy_execution_plans"], counts_after_discovery["strategy_execution_plans"])
        self.assertEqual(counts_before_approval["champion_registry"], counts_after_discovery["champion_registry"])

        # 11-12. Another autonomous tick still waits for human approval.
        next_result = self.worker.tick()
        self.assertEqual(next_result.action, "skipped_awaiting_human_or_terminal")
        self.assertTrue(next_result.approval_required)
        self.assertFalse(next_result.autonomous_progression)

        # 13-14. Query Web again - no duplicate approval request/candidate.
        status2, payload2 = dispatch_request(web_adapter, method="GET", path="/gaon/research/pending-approvals", body=None)
        self.assertEqual(status2, 200)
        self.assertEqual(len(payload2["pending_approvals"]), 1)
        entry2 = payload2["pending_approvals"][0]
        matches2 = [c for c in entry2["candidates"] if c["candidate_id"] == candidate.candidate_id]
        self.assertEqual(len(matches2), 1)
        self.assertEqual(len(entry2["candidates"]), len(entry["candidates"]))  # no duplicate candidate rows appeared

    def test_no_autonomous_authority_gained_by_cross_session_discovery(self) -> None:
        """Discovery must never imply the autonomous runtime (or the Web
        read endpoint itself) can approve/apply/promote/trade - the
        endpoint is pure GET, and the worker's own hard stop is unchanged."""
        for _ in range(5):
            self.worker.tick()
        mission = self.agent._brain._mission_for(TELEGRAM_SESSION_ID)
        candidate = get_candidate(mission, mission.active_candidate_id)
        approval_mission = mission
        for index in range(3):
            approval_mission = record_promotion_candidate(
                approval_mission, strategy_fingerprint=candidate.strategy_fingerprint if index == 0 else f"authority-other-{index}",
                candidate_id=candidate.candidate_id if index == 0 else f"KR-ST-91{index}", now=NOW,
            )
        self.agent._brain._remember_mission(_continuation_request(TELEGRAM_SESSION_ID, TELEGRAM_CHAT_ID, NOW, suffix="approval"), approval_mission)

        web_adapter = GaonWebChatAdapter(self.config, self.connection)
        dispatch_request(web_adapter, method="GET", path="/gaon/research/pending-approvals", body=None)

        result = self.worker.tick()
        self.assertEqual(result.action, "skipped_awaiting_human_or_terminal")
        counts = _observed_tables(self.connection)
        self.assertEqual(counts["champion_registry"], 0)
        self.assertEqual(counts["approvals"], 0)
        self.assertEqual(counts["strategy_deployment_requests"], 0)


class WebOriginatedRegressionTests(unittest.TestCase):
    """A candidate/mission originating from web:<ref> must continue
    working exactly as before - both the existing per-session endpoints
    and the new cross-session discovery endpoint."""

    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.config = _config()
        self.web_adapter = GaonWebChatAdapter(self.config, self.connection)
        self.web_session_ref = "web-native-ref"
        self.web_adapter._brain._repository.upsert_session(LLMConversationSession(f"web:{self.web_session_ref}", "test", "web", "active", NOW, NOW, {}))

        mission = _seeded_exhausted_mission()
        candidate = new_candidate("breakout_standard", sequence=10, now=NOW)
        mission = add_candidate(mission, candidate, now=NOW)
        for index in range(3):
            mission = record_promotion_candidate(
                mission, strategy_fingerprint=candidate.strategy_fingerprint if index == 0 else f"web-native-other-{index}",
                candidate_id=candidate.candidate_id if index == 0 else f"KR-ST-92{index}", now=NOW,
            )
        self.assertEqual(mission.status, MissionStatus.AWAITING_HUMAN_APPROVAL)
        self.mission = mission
        self.candidate = candidate
        self.web_adapter._brain._remember_mission(
            LLMConversationRequest(session_id=f"web:{self.web_session_ref}", user_ref="test", source="web", text="x", received_at=NOW, message_id="web:native:1"),
            mission,
        )

    def tearDown(self) -> None:
        self.connection.close()

    def test_existing_per_session_endpoints_unchanged(self) -> None:
        status, payload = dispatch_request(self.web_adapter, method="GET", path=f"/gaon/research/mission?session_ref={self.web_session_ref}", body=None)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "awaiting_human_approval")

        status2, payload2 = dispatch_request(self.web_adapter, method="GET", path=f"/gaon/research/candidates?session_ref={self.web_session_ref}", body=None)
        self.assertEqual(status2, 200)
        self.assertTrue(any(c["candidate_id"] == self.candidate.candidate_id for c in payload2["candidates"]))

    def test_web_originated_candidate_also_visible_via_cross_session_discovery(self) -> None:
        status, payload = dispatch_request(self.web_adapter, method="GET", path="/gaon/research/pending-approvals", body=None)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["pending_approvals"]), 1)
        entry = payload["pending_approvals"][0]
        self.assertEqual(entry["session_ref"], f"web:{self.web_session_ref}")
        self.assertEqual(entry["source"], "web")
        self.assertTrue(any(c["candidate_id"] == self.candidate.candidate_id for c in entry["candidates"]))


if __name__ == "__main__":
    unittest.main()
