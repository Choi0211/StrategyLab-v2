"""fix/web-conversation-family-coverage-read.

Production symptom (read-only Web dashboard, owner correctly configured, a
durable KR / market-wide / 단타 ResearchMission with 16 real candidates):

  "단타 연구 잘되고 있어?"        -> resolved the durable owner mission, KR-ST-* listed
  "그중 제일 좋은 건?"            -> resolved it too, KR-ST-001..016 shown
  "돌파 말고 다른 전략도 연구하고 있어?" -> "현재 검증 중인 전략 후보가 없습니다"
                                    (contradicts the two turns above)

Root cause: ``_is_conversational_mvp_source``'s admission gate for a
read_only=True Web message only admitted ``is_research_progress_status_
question`` / ``is_mission_candidate_read_request``. A read-only
``is_best_candidate_query`` ("그중 제일 좋은 건?") or
``is_strategy_family_coverage_question`` ("돌파 말고 다른 전략도 연구하고
있어?") was excluded from the conversational-MVP pipeline, never resolved
the durable owner mission, and was answered by a mission-unaware generic
path.

This test locks in: every read-only Web question of those shapes resolves
the SAME durable owner mission, the candidate portfolio never
"disappears" between routes, the family question is answered TRUTHFULLY
from persisted state (relative strength stays fail-closed without an
explicit peer context), a true same-session follow-up keeps its subject,
and nothing is mutated.
"""

from __future__ import annotations

import unittest

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import (
    add_candidate,
    extract_or_update_mission,
    next_candidate_sequence,
    set_active_candidate,
)
from gaon.knowledge.strategy_candidate import new_candidate
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationRequest
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter, dispatch_request

NOW = "2026-09-07T00:00:00Z"
OWNER_CHAT_ID = "8767020479"
OWNER_WEB_REF = "binance-dashboard-operator"
OWNER_REF = "youngha-owner"

_MISSION_AWARE_ROUTES = {
    "conversation_mission_candidate_read",
    "conversation_mission_status_read",
    "conversation_mission_candidates_overview",
    "conversation_mission_family_coverage",
    "conversation_mission_subject_explanation",
    "conversation_mission_no_active_candidate",
    "conversation_mission_blocked",
}


def _config() -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        telegram_allowed_chat_ids=(OWNER_CHAT_ID,),
        owner_ref=OWNER_REF,
        owner_telegram_chat_ids=(OWNER_CHAT_ID,),
        owner_web_user_refs=(OWNER_WEB_REF,),
        assistant_enabled=True,
        assistant_provider="deterministic",
    )


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id, text, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id="x", message_id=str(len(self.sent)))


def _tg_update(uid: int, text: str) -> dict:
    return {"update_id": uid, "message": {"message_id": uid, "chat": {"id": int(OWNER_CHAT_ID)}, "from": {"id": int(OWNER_CHAT_ID + "9")}, "text": text}}


def _seed_durable_owner_mission(config, connection, *, families: list[str], with_active: bool) -> "object":
    mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
    last_id = None
    for family in families:
        candidate = new_candidate(family, sequence=next_candidate_sequence(mission), now=NOW)
        mission = add_candidate(mission, candidate, now=NOW)
        last_id = candidate.candidate_id
    if with_active and last_id is not None:
        mission = set_active_candidate(mission, last_id, now=NOW)
    agent = TelegramConversationAgent(config, connection)
    runtime = TelegramRuntime(agent, allowed_chat_ids=(OWNER_CHAT_ID,))
    process_update(parse_update_result(_tg_update(0, "안녕하세요"), received_at=NOW), runtime, _FakeTelegramClient())
    agent._brain._remember_mission(
        LLMConversationRequest(session_id=f"telegram:{OWNER_CHAT_ID}", user_ref=f"telegram-user:{OWNER_CHAT_ID}", source="telegram", text="x", received_at=NOW),
        mission,
    )
    return mission


class _Fixture(unittest.TestCase):
    FAMILIES = ["breakout_standard", "breakout_trend_confirmed", "mean_reversion_standard", "momentum_roc_standard"]
    WITH_ACTIVE = True

    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.config = _config()
        self.mission = _seed_durable_owner_mission(self.config, self.store._connection, families=self.FAMILIES, with_active=self.WITH_ACTIVE)
        self.adapter = GaonWebChatAdapter(self.config, self.store._connection)

    def _chat(self, text: str, *, session_ref: str, read_only: bool = True) -> dict:
        return dict(self.adapter.handle(message=text, session_ref=session_ref, user_ref=OWNER_WEB_REF, read_only=read_only, received_at=NOW))

    def _owning_metadata(self) -> str:
        row = self.store._connection.execute(
            "SELECT metadata_json FROM conversation_sessions WHERE session_id = ?", (f"telegram:{OWNER_CHAT_ID}",)
        ).fetchone()
        return row[0]

    def _assert_safe(self, resp: dict) -> None:
        self.assertFalse(resp["strategy_mutated"])
        self.assertFalse(resp["order_executed"])
        self.assertFalse(resp.get("approval_required"))
        self.assertEqual(list(resp["tool_calls"]), [])


class IndependentReadOnlySessionsResolveTheSameMission(_Fixture):
    def test_every_read_only_question_shape_resolves_the_durable_owner_mission(self) -> None:
        for i, question in enumerate(
            [
                "단타 연구 잘되고 있어?",
                "그중 제일 좋은 건?",
                "돌파 말고 다른 전략도 연구하고 있어?",
                "그중에서 상대강도 전략은?",
            ]
        ):
            resp = self._chat(question, session_ref=f"indep-{i}")
            with self.subTest(question=question):
                self.assertIn(resp["route"], _MISSION_AWARE_ROUTES, resp["text"][:200])
                self.assertTrue(
                    any(w.startswith(f"durable_owner_mission_resolved={self.mission.mission_id}") for w in resp["warnings"]),
                    resp["warnings"],
                )
                self.assertNotIn("아직 생성된 전략 후보가 없습니다", resp["text"])
                self.assertNotIn("전략 후보가 생성되지 않았습니다", resp["text"])
                self._assert_safe(resp)

    def test_family_question_never_says_no_candidates_when_candidates_exist(self) -> None:
        resp = self._chat("돌파 말고 다른 전략도 연구하고 있어?", session_ref="fam")
        self.assertEqual(resp["route"], "conversation_mission_family_coverage")
        # the two families that DO have candidates are named
        self.assertIn("mean_reversion_standard", resp["text"])
        self.assertIn("momentum_roc_standard", resp["text"])
        # a family with no candidate is an available direction, not "being researched"
        self.assertIn("volatility_thrust_standard", resp["text"])
        self.assertIn("연구 방향", resp["text"])
        self.assertNotIn("현재 검증 중인 전략 후보가 없습니다", resp["text"])

    def test_relative_strength_reported_fail_closed_without_explicit_peers(self) -> None:
        resp = self._chat("돌파 말고 다른 전략도 연구하고 있어?", session_ref="rs")
        self.assertIn("relative_strength_requires_multi_symbol_context", resp["text"])
        self.assertIn("가짜 peer", resp["text"])

    def test_read_only_family_question_does_not_mutate_the_mission(self) -> None:
        before = self._owning_metadata()
        self._chat("돌파 말고 다른 전략도 연구하고 있어?", session_ref="nomut")
        self._chat("평균회귀나 모멘텀 전략도 연구 중이야?", session_ref="nomut2")
        self.assertEqual(before, self._owning_metadata())


class TrueSameSessionFollowUpContinuity(_Fixture):
    def test_five_turn_same_session_sequence(self) -> None:
        s = "same-session"
        r1 = self._chat("단타 연구 잘되고 있어?", session_ref=s)
        r2 = self._chat("그중 제일 좋은 건?", session_ref=s)
        r3 = self._chat("왜?", session_ref=s)
        r4 = self._chat("돌파 말고 다른 전략도 연구하고 있어?", session_ref=s)
        r5 = self._chat("그중에서 상대강도 전략은?", session_ref=s)

        for r in (r1, r2, r3, r4, r5):
            self.assertIn(r["route"], _MISSION_AWARE_ROUTES, r["text"][:200])
            self.assertTrue(any(w.startswith("durable_owner_mission_resolved=") for w in r["warnings"]))
            self._assert_safe(r)

        self.assertEqual(r2["route"], "conversation_mission_candidates_overview")
        self.assertIn("가장 좋다", r2["text"])  # explicitly declines to rank
        self.assertEqual(r3["route"], "conversation_mission_subject_explanation")  # "왜?" keeps the prior subject
        self.assertEqual(r4["route"], "conversation_mission_family_coverage")
        self.assertEqual(r5["route"], "conversation_mission_family_coverage")
        self.assertIn("relative_strength", r5["text"])

    def test_independent_sessions_share_the_mission_not_the_conversation(self) -> None:
        a = self._chat("돌파 말고 다른 전략도 연구하고 있어?", session_ref="A")
        # a bare "왜?" in a DIFFERENT fresh session has no prior subject there
        b = self._chat("왜?", session_ref="B")
        self.assertEqual(a["route"], "conversation_mission_family_coverage")
        self.assertNotEqual(b["route"], "conversation_mission_family_coverage")


class MissionWithNoActiveCandidate(_Fixture):
    WITH_ACTIVE = False

    def test_family_question_still_answers_from_the_16_candidates(self) -> None:
        resp = self._chat("돌파 말고 다른 전략도 연구하고 있어?", session_ref="noactive")
        self.assertEqual(resp["route"], "conversation_mission_family_coverage")
        self.assertIn("mean_reversion_standard", resp["text"])
        self.assertNotIn("아직 생성된 전략 후보가 없습니다", resp["text"])


class MissionStatusHttpContract(_Fixture):
    def test_missing_session_ref_still_returns_the_explicit_validation_error(self) -> None:
        status, payload = dispatch_request(self.adapter, method="GET", path="/gaon/research/mission", body=None)
        self.assertEqual(status, 400)
        self.assertIn("session_ref", payload["error"])

    def test_session_ref_plus_owner_user_ref_returns_the_durable_owner_mission(self) -> None:
        status, payload = dispatch_request(
            self.adapter,
            method="GET",
            path=f"/gaon/research/mission?session_ref=fresh-dashboard-panel&user_ref={OWNER_WEB_REF}",
            body=None,
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["exists"])
        self.assertEqual(payload["mission_id"], self.mission.mission_id)
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])

    def test_session_ref_without_owner_user_ref_stays_session_local(self) -> None:
        status, payload = dispatch_request(
            self.adapter, method="GET", path="/gaon/research/mission?session_ref=stranger-session", body=None
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["exists"])

    def test_non_owner_user_ref_does_not_resolve_the_owner_mission(self) -> None:
        status, payload = dispatch_request(
            self.adapter,
            method="GET",
            path="/gaon/research/mission?session_ref=x&user_ref=someone-else",
            body=None,
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["exists"])


if __name__ == "__main__":
    unittest.main()
