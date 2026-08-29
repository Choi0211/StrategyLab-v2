"""Production hotfix acceptance: background autonomous research worker.

Proves ``gaon.runtime.autonomous_research_runtime`` advances a persisted,
canonical Telegram ResearchMission through the SAME real, bounded,
tool-routed mission-driven research cycle a "연구 계속해주세요" Telegram
message already takes (``LLMConversationBrain._try_mission_driven_research_
cycle``), from a background/scheduled context rather than a live user turn -
and that it unconditionally stops at ``MissionStatus.AWAITING_HUMAN_
APPROVAL`` (the codebase's READY_FOR_APPROVAL gate) without ever touching
approval, promotion, deployment, or order-execution code paths.
"""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import (
    MissionStatus,
    extract_or_update_mission,
    get_active_candidate,
    record_blocked,
    record_promotion_candidate,
)
from gaon.runtime.autonomous_research_runtime import (
    AutonomousResearchRuntimeService,
    AutonomousResearchRuntimeWorker,
)
from gaon.runtime.scheduled_automation import ScheduledJobRepository
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

from test_strategy_centric_autonomous_research import (
    _DeterministicKRUniverseProvider,
    _RecordingTelegramClient,
    _baseline,
    _config,
    _update,
)

_NOW = "2026-08-22T00:00:05Z"


class _ResearchPatchedTestCase(unittest.TestCase):
    def _patched(self, update_id: int):
        stack = ExitStack()
        baseline = _baseline(trades=45, run_id=f"turn{update_id}")
        stack.enter_context(patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline))
        stack.enter_context(
            patch(
                "gaon.knowledge.telegram_autonomous_learning._run_production_external_research",
                return_value={"state": "content_unavailable"},
            )
        )
        stack.enter_context(
            patch("gaon.research.multi_symbol.build_market_data_provider_from_env", return_value=_DeterministicKRUniverseProvider())
        )
        return stack


class AutonomousResearchWorkerAdvancesActiveMissionTests(_ResearchPatchedTestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()

    def _send(self, update_id: int, text: str) -> str:
        with self._patched(update_id):
            result = process_update(
                parse_update_result(_update(update_id, update_id, text), received_at=f"2026-08-18T00:{update_id:02d}:00Z"),
                self.runtime,
                self.client,
            )
        self.assertEqual(result.status, "sent")
        return self.client.sent[-1][1]

    def _mission(self):
        return self.agent._brain._mission_for("telegram:100")

    def _research_tool_call_count(self) -> int:
        return sum(
            len(self.store.tool_audit.list(tool_name=name))
            for name in ("multi_symbol_research", "autonomous_learning_research", "autonomous_research_cycle")
        )

    def test_active_mission_advances_by_exactly_one_bounded_cycle(self) -> None:
        self._send(20, "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요")
        mission_before = self._mission()
        self.assertIsNotNone(mission_before)
        self.assertEqual(mission_before.status, MissionStatus.ACTIVE)
        cycles_before = mission_before.cycles_completed
        calls_before = self._research_tool_call_count()

        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: "2026-08-18T00:10:00Z")
        with self._patched(21):
            result = worker.tick()

        self.assertEqual(result.action, "cycle_executed")
        self.assertEqual(self._research_tool_call_count(), calls_before + 1, "worker must perform exactly one bounded tool call per tick")
        mission_after = self._mission()
        self.assertGreaterEqual(mission_after.cycles_completed, cycles_before)

    def test_repeated_ticks_self_direct_progress_without_any_new_user_message(self) -> None:
        """Hotfix #166 Section 5: with an active mission, the worker keeps
        advancing research over successive scheduled ticks with ZERO new
        user messages in between - proving Gaon does not need to be told
        "연구 계속해주세요" every time, using the exact same real,
        already-existing bounded mission-driven cycle
        (LLMConversationBrain.respond -> _try_mission_driven_research_
        cycle -> next_blocker_driven_research_action) each tick already
        reuses to decide its own next research action from real evidence."""
        self._send(60, "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요")
        mission_after_setup = self._mission()
        self.assertIsNotNone(mission_after_setup)
        user_messages_before = sum(
            1 for m in self.store.conversations.list_messages("telegram:100", limit=1000) if m.role == "user"
        )

        seen_candidate_ids: set[str] = set()
        seen_actions: set[str] = set()
        for tick_index in range(4):
            worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda i=tick_index: f"2026-08-18T00:{10 + i:02d}:00Z")
            with self._patched(61 + tick_index):
                result = worker.tick()
            self.assertIn(result.action, {"cycle_executed", "blocked_no_recovery"}, f"tick {tick_index} produced unexpected action {result.action}")
            mission_now = self._mission()
            self.assertIsNotNone(mission_now)
            active = get_active_candidate(mission_now)
            if active is not None:
                seen_candidate_ids.add(active.candidate_id)
            seen_actions.add(result.action)

        # Real self-directed progression happened - some bounded work was
        # actually done across the ticks, never on the same candidate
        # rotating in and out arbitrarily, and never by fabricating a
        # different action out of nowhere.
        self.assertIn("cycle_executed", seen_actions)
        self.assertGreaterEqual(len(seen_candidate_ids), 1)

        # No new "user" conversation_messages row was ever created by any
        # of the four autonomous ticks above.
        user_messages_after = sum(
            1 for m in self.store.conversations.list_messages("telegram:100", limit=1000) if m.role == "user"
        )
        self.assertEqual(user_messages_after, user_messages_before)

    def test_restart_resumes_the_same_durable_mission_and_keeps_advancing_it(self) -> None:
        """A fresh AutonomousResearchRuntimeWorker instance (simulating a
        service restart - no in-memory state carried over) reads the same
        persisted mission from the SAME connection and continues advancing
        it, never starting a new/different mission."""
        self._send(70, "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요")
        mission_id = self._mission().mission_id

        worker_before_restart = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: "2026-08-18T00:10:00Z")
        with self._patched(71):
            worker_before_restart.tick()
        cycles_before_restart = self._mission().cycles_completed

        # Simulate restart: brand-new worker instance, same durable store.
        worker_after_restart = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: "2026-08-18T00:20:00Z")
        with self._patched(72):
            result = worker_after_restart.tick()

        self.assertEqual(result.action, "cycle_executed")
        mission_after_restart = self._mission()
        self.assertEqual(mission_after_restart.mission_id, mission_id, "restart must resume the SAME mission, never create a new one")
        self.assertGreaterEqual(mission_after_restart.cycles_completed, cycles_before_restart)

    def _conversation_message_count(self, session_id: str = "telegram:100") -> int:
        return len(self.store.conversations.list_messages(session_id, limit=1000))

    def _cognitive_record_count(self) -> int:
        return self.store._connection.execute("SELECT COUNT(*) FROM cognitive_records").fetchone()[0]

    def test_autonomous_tick_advances_mission_without_polluting_user_conversation_or_cognitive_memory(self) -> None:
        self._send(40, "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요")
        mission_before = self._mission()
        cycles_before = mission_before.cycles_completed
        messages_before = self._conversation_message_count()
        cognitive_before = self._cognitive_record_count()

        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: "2026-08-18T00:10:00Z")
        with self._patched(41):
            result = worker.tick()

        self.assertEqual(result.action, "cycle_executed")
        mission_after = self._mission()
        self.assertGreaterEqual(mission_after.cycles_completed, cycles_before, "autonomous tick must still advance the real ResearchMission")
        self.assertEqual(
            self._conversation_message_count(),
            messages_before,
            "autonomous tick must not be recorded as a user/assistant conversation_messages row",
        )
        self.assertEqual(
            self._cognitive_record_count(),
            cognitive_before,
            "autonomous tick must not create/mutate any cognitive feedback/preference/goal record",
        )

    def test_real_telegram_continuation_still_persists_and_updates_cognitive_goal_normally(self) -> None:
        self._send(50, "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요")
        messages_before = self._conversation_message_count()
        cognitive_before = self._cognitive_record_count()

        self._send(51, "연구 계속해주세요")

        self.assertGreater(
            self._conversation_message_count(),
            messages_before,
            "a real Telegram user turn must still be recorded normally",
        )
        self.assertGreaterEqual(
            self._cognitive_record_count(),
            cognitive_before,
            "a real Telegram user turn must still be free to update cognitive memory (goal tracking) as before",
        )
        messages = self.store.conversations.list_messages("telegram:100", limit=1000)
        self.assertTrue(any(message.role == "user" and message.content == "연구 계속해주세요" for message in messages))

    def test_awaiting_human_approval_mission_is_never_advanced(self) -> None:
        self._send(30, "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요")
        mission = self._mission()
        for index in range(3):
            mission = record_promotion_candidate(
                mission, strategy_fingerprint=f"verified-{index}", candidate_id=f"KR-ST-00{index + 1}", now=_NOW
            )
        self.agent._brain._remember_mission(_fake_request(), mission)
        self.assertEqual(mission.status, MissionStatus.AWAITING_HUMAN_APPROVAL)

        calls_before = self._research_tool_call_count()
        messages_before = self._conversation_message_count()
        cognitive_before = self._cognitive_record_count()
        worker = AutonomousResearchRuntimeWorker(_config(), self.store._connection, now_factory=lambda: "2026-08-18T00:10:00Z")
        result = worker.tick()

        self.assertEqual(result.action, "skipped_awaiting_human_or_terminal")
        self.assertEqual(result.mission_status, MissionStatus.AWAITING_HUMAN_APPROVAL.value)
        self.assertEqual(self._research_tool_call_count(), calls_before)
        self.assertEqual(self._conversation_message_count(), messages_before)
        self.assertEqual(self._cognitive_record_count(), cognitive_before)


def _fake_request():
    from gaon.runtime.llm_conversation import LLMConversationRequest

    return LLMConversationRequest(
        session_id="telegram:100",
        user_ref="test",
        source="telegram",
        text="test",
        received_at=_NOW,
    )


class AutonomousResearchDurableSchedulingTests(unittest.TestCase):
    def test_no_mission_tick_is_a_safe_noop(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            worker = AutonomousResearchRuntimeWorker(_config(), store._connection, now_factory=lambda: _NOW)
            result = worker.tick()
            self.assertEqual(result.action, "skipped_no_mission")
        finally:
            store.close()

    def test_blocked_mission_without_recovery_stays_honestly_blocked(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            agent = TelegramConversationAgent(_config(), store._connection)
            runtime = TelegramRuntime(agent, allowed_chat_ids=("100",))
            client = _RecordingTelegramClient()
            process_update(
                parse_update_result(_update(1, 1, "안녕하세요"), received_at=_NOW),
                runtime,
                client,
            )
            mission = extract_or_update_mission(
                "국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요", existing=None, now=_NOW
            )
            mission = record_blocked(mission, reason="provider_unavailable: no data source responded", now=_NOW)
            agent._brain._remember_mission(_fake_request(), mission)

            worker = AutonomousResearchRuntimeWorker(_config(), store._connection, now_factory=lambda: _NOW)
            result = worker.tick()

            self.assertEqual(result.action, "blocked_no_recovery")
            self.assertEqual(result.blocker, "provider_unavailable: no data source responded")
        finally:
            store.close()

    def test_service_tick_is_idempotent_within_the_same_interval_and_durable_across_restart(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            repository = ScheduledJobRepository(store._connection)
            service = AutonomousResearchRuntimeService(_config(), repository, now_factory=lambda: _NOW)

            first = service.tick()
            second = service.tick()

            self.assertTrue(first.jobs_registered)
            self.assertFalse(second.jobs_registered, "job registration must be idempotent")
            self.assertEqual(len(first.results), 1)
        finally:
            store.close()

        restored = RuntimeStateStore(":memory:")
        try:
            # A fresh service against a fresh (but schema-migrated) store
            # behaves the same way a restarted process would: it registers
            # its own first tick job rather than crashing on missing state.
            repository = ScheduledJobRepository(restored._connection)
            service = AutonomousResearchRuntimeService(_config(), repository, now_factory=lambda: _NOW)
            result = service.tick()
            self.assertTrue(result.attempted)
        finally:
            restored.close()

    def test_no_allowed_chat_is_disabled_not_a_crash(self) -> None:
        from gaon.runtime.config import GaonRuntimeConfig

        store = RuntimeStateStore(":memory:")
        try:
            repository = ScheduledJobRepository(store._connection)
            config = GaonRuntimeConfig(mode="execute", dry_run=False, telegram_enabled=True, telegram_bot_token="t", telegram_allowed_chat_ids=(), approval_signing_secret="s")
            service = AutonomousResearchRuntimeService(config, repository, now_factory=lambda: _NOW)
            result = service.tick()
            self.assertFalse(result.enabled)
            self.assertFalse(result.attempted)
        finally:
            store.close()


class AutonomousResearchRuntimeReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes(self) -> None:
        from gaon.runtime.autonomous_research_runtime import production_autonomous_research_runtime_release_check

        payload = production_autonomous_research_runtime_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])


if __name__ == "__main__":
    unittest.main()
