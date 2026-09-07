"""PR #213 - Conversation Integrity & General Autonomous Conversation.

Regression coverage for three user-reported production bugs:

BUG A  A read-only Web/Telegram conversation mutated ResearchMission
       operational fields (``status`` blocked->active, ``updated_at``
       refreshed) even though no tool ran and no research executed.

BUG B  An explanation/rephrase follow-up ("이유를 한글로 알아들을수있게
       말해주세요") right after a blocked-status answer launched unrelated
       research on a leftover symbol and exposed the raw internal blocker
       code.

BUG C  Follow-ups only worked for a handful of hard-coded phrases; broader
       natural questions ("왜?", "그게 무슨 뜻이야?", "쉽게 설명해줘",
       "현재 진행상황 알려줘", ...) lost the conversational subject.

The fix is a general INTERPRET / RESOLVE / AUTHORIZE layer: a read-only
turn never mutates operational state and never routes to research; the
AUTHORIZE stage stays deterministic (an explicit "다시 연구해줘" /
"검증해줘"); the blocked reason is explained in natural Korean through one
centralized path with the raw code hidden unless technical detail is
explicitly requested.
"""

from __future__ import annotations

import json
import unittest

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import (
    MissionStatus,
    add_candidate,
    extract_or_update_mission,
    next_candidate_sequence,
    record_blocked,
    set_active_candidate,
)
from gaon.knowledge.strategy_candidate import new_candidate
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationRequest
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-09-07T00:00:00Z"
OWNER_CHAT_ID = "8767020479"
OWNER_WEB_REF = "binance-dashboard-operator"
OWNER_REF = "youngha-owner"
RAW_BLOCKER = "strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted"

_MISSION_AWARE_ROUTES = {
    "conversation_mission_candidate_read",
    "conversation_mission_status_read",
    "conversation_mission_candidates_overview",
    "conversation_mission_family_coverage",
    "conversation_mission_subject_explanation",
    "conversation_mission_no_active_candidate",
    "conversation_mission_blocked",
}
_UNRELATED_TEST_SYMBOL = "000370"


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


def _seed_blocked_owner_mission(config, connection, *, with_active: bool = True):
    mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
    last_id = None
    for family in ("breakout_standard", "breakout_trend_confirmed", "mean_reversion_standard"):
        candidate = new_candidate(family, sequence=next_candidate_sequence(mission), now=NOW)
        mission = add_candidate(mission, candidate, now=NOW)
        last_id = candidate.candidate_id
    if with_active and last_id is not None:
        mission = set_active_candidate(mission, last_id, now=NOW)
    mission = record_blocked(mission, reason=RAW_BLOCKER, now=NOW)
    mission = mission.__class__(**{**mission.__dict__, "cycles_completed": 61})

    agent = TelegramConversationAgent(config, connection)
    runtime = TelegramRuntime(agent, allowed_chat_ids=(OWNER_CHAT_ID,))
    process_update(parse_update_result(_tg_update(0, "안녕하세요"), received_at=NOW), runtime, _FakeTelegramClient())
    agent._brain._remember_mission(
        LLMConversationRequest(session_id=f"telegram:{OWNER_CHAT_ID}", user_ref=f"telegram-user:{OWNER_CHAT_ID}", source="telegram", text="x", received_at=NOW),
        mission,
    )
    return mission, agent, runtime


def _mission_snapshot(connection) -> dict:
    row = connection.execute(
        "SELECT metadata_json FROM conversation_sessions WHERE session_id = ?", (f"telegram:{OWNER_CHAT_ID}",)
    ).fetchone()
    m = json.loads(row[0])["conversation_mvp"]["research_mission"]
    return {
        "mission_id": m["mission_id"],
        "status": m["status"],
        "candidate_count": len(m.get("candidates", ())),
        "candidate_ids": [c.get("candidate_id") for c in m.get("candidates", ())],
        "cycles_completed": m["cycles_completed"],
        "blocked_reason": m["blocked_reason"],
        "updated_at": m["updated_at"],
    }


class _Base(unittest.TestCase):
    WITH_ACTIVE = True

    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.conn = self.store._connection
        self.config = _config()
        self.mission, self.agent, self.runtime = _seed_blocked_owner_mission(self.config, self.conn, with_active=self.WITH_ACTIVE)
        self.adapter = GaonWebChatAdapter(self.config, self.conn)

    def _web(self, text: str, *, session_ref: str, read_only: bool = True, at: str = NOW) -> dict:
        return dict(self.adapter.handle(message=text, session_ref=session_ref, user_ref=OWNER_WEB_REF, read_only=read_only, received_at=at))

    def _tg(self, uid: int, text: str, *, at: str = NOW) -> str:
        client = _FakeTelegramClient()
        process_update(parse_update_result(_tg_update(uid, text), received_at=at), self.runtime, client)
        return client.sent[-1][1]

    def _tg_response(self, uid: int, text: str, *, at: str = NOW):
        return self.agent._brain.respond(
            LLMConversationRequest(
                session_id=f"telegram:{OWNER_CHAT_ID}",
                user_ref=f"telegram-user:{OWNER_CHAT_ID}",
                source="telegram",
                text=text,
                received_at=at,
                message_id=f"telegram:{OWNER_CHAT_ID}:{uid}",
            )
        )

    def _assert_safe(self, resp: dict) -> None:
        self.assertFalse(resp["strategy_mutated"])
        self.assertFalse(resp["order_executed"])
        self.assertFalse(resp.get("approval_required"))
        self.assertEqual(list(resp["tool_calls"]), [])


class BugA_ReadOnlyDoesNotMutateMission(_Base):
    def test_read_only_web_conversation_leaves_every_operational_field_unchanged(self) -> None:
        before = _mission_snapshot(self.conn)
        for i, q in enumerate(
            [
                "단타 연구는 진행되고있나요",
                "이유를 한글로 알아들을수있게 말해주세요",
                "현재 진행상황 알려주세요",
                "그중 제일 좋은 건?",
                "왜?",
            ],
            start=1,
        ):
            resp = self._web(q, session_ref="webE2E", at=f"2026-09-07T00:0{i}:00Z")
            self.assertIn(resp["route"], _MISSION_AWARE_ROUTES, resp["text"][:200])
            self._assert_safe(resp)
        after = _mission_snapshot(self.conn)
        self.assertEqual(before, after)
        # explicit per-field assertions from the bug report
        for field in ("mission_id", "status", "candidate_count", "candidate_ids", "cycles_completed", "blocked_reason", "updated_at"):
            self.assertEqual(before[field], after[field], field)
        self.assertEqual(after["status"], "blocked")
        self.assertEqual(after["updated_at"], NOW)

    def test_read_only_telegram_status_reads_do_not_refresh_updated_at(self) -> None:
        before = _mission_snapshot(self.conn)
        self._tg(1, "단타 연구는 진행되고있나요", at="2026-09-07T01:00:00Z")
        self._tg(2, "현재 진행상황 알려주세요", at="2026-09-07T02:00:00Z")
        self._tg(3, "그게 무슨 뜻이야?", at="2026-09-07T03:00:00Z")
        after = _mission_snapshot(self.conn)
        self.assertEqual(before, after)


class BugB_ExplanationFollowupStaysOnSubject(_Base):
    SEQ = ["안녕하세요", "단타 연구는 진행되고있나요", "이유를 한글로 알아들을수있게 말해주세요", "현재 진행상황 알려주세요"]

    def test_korean_explanation_preserves_the_same_blocked_reason_and_runs_no_research(self) -> None:
        before = _mission_snapshot(self.conn)
        texts = [self._tg(i + 1, q, at=f"2026-09-07T0{i}:00:00Z") for i, q in enumerate(self.SEQ)]
        greeting, status_answer, explain_answer, status_again = texts

        # status answer explains the blocked mission without the raw code
        self.assertNotIn(RAW_BLOCKER, status_answer)
        self.assertNotIn("strategy_hypothesis_space_exhausted", status_answer)

        # the explanation follow-up keeps the SAME blocked reason, in natural Korean
        self.assertIn("더 확장할 후보가 남아 있지 않아", explain_answer)
        self.assertNotIn("strategy_hypothesis_space_exhausted", explain_answer)
        self.assertNotIn("bounded declarative", explain_answer)

        # no unrelated symbol, no fabricated research
        for t in (explain_answer, status_again):
            self.assertNotIn(_UNRELATED_TEST_SYMBOL, t)
            self.assertNotIn("전략을 다시 연구했습니다", t)

        # mission completely unchanged
        self.assertEqual(before, _mission_snapshot(self.conn))

    def test_no_research_tool_call_for_the_explanation_follow_up(self) -> None:
        for i, q in enumerate(self.SEQ):
            resp = self._tg_response(i + 1, q, at=f"2026-09-07T0{i}:00:00Z")
        self.assertEqual(list(resp.tool_calls), [])
        self.assertNotIn(resp.route, {"conversation_autonomous_research_cycle", "conversation_autonomous_learning_v2"})

    def test_raw_blocker_code_can_still_be_surfaced_on_an_explicit_technical_request(self) -> None:
        self._tg(1, "단타 연구는 진행되고있나요")
        technical = self._tg(2, "그 blocker 코드 원문 그대로 알려줘")
        self.assertIn(RAW_BLOCKER, technical)


class BugC_BroaderNaturalConversation(_Base):
    def test_a_variety_of_natural_followups_stay_grounded_and_read_only(self) -> None:
        # establish the subject
        first = self._tg_response(1, "단타 연구는 진행되고있나요")
        self.assertIn(first.route, _MISSION_AWARE_ROUTES)
        for i, q in enumerate(
            [
                "왜?",
                "그게 무슨 뜻이야?",
                "쉽게 설명해줘",
                "한글로 설명해줘",
                "이유를 말해줘",
                "현재 진행상황 알려줘",
            ],
            start=2,
        ):
            resp = self._tg_response(i, q, at=f"2026-09-07T00:0{i}:00Z")
            with self.subTest(q=q):
                self.assertIn(resp.route, _MISSION_AWARE_ROUTES, f"{q} -> {resp.route}: {resp.text[:160]}")
                self.assertEqual(list(resp.tool_calls), [])
                self.assertNotIn("strategy_hypothesis_space_exhausted", resp.text)

    def test_why_after_a_candidate_comparison_keeps_that_subject(self) -> None:
        self._tg_response(1, "단타 연구는 진행되고있나요")
        overview = self._tg_response(2, "그중 제일 좋은 건?")
        self.assertEqual(overview.route, "conversation_mission_candidates_overview")
        why = self._tg_response(3, "왜?")
        self.assertEqual(why.route, "conversation_mission_subject_explanation")
        self.assertEqual(list(why.tool_calls), [])

    def test_explicit_research_request_is_still_distinguishable_from_explanation(self) -> None:
        # "그거 더 연구해줘" is an explicit state-changing request - it must
        # NOT be swallowed by the read-only subject-explanation path.
        self._tg_response(1, "단타 연구는 진행되고있나요")
        resp = self._tg_response(2, "그거 더 연구해줘")
        self.assertNotEqual(resp.route, "conversation_mission_subject_explanation")


class UnrelatedSymbolInjection(_Base):
    def test_status_followup_never_introduces_an_unrelated_symbol(self) -> None:
        # prime a stale single-symbol research context on the SAME session,
        # then ask an explanation follow-up: the leftover symbol must not
        # leak into the answer.
        self._tg(1, "단타 연구는 진행되고있나요")
        answers = [
            self._tg(2, "이유를 한글로 알아들을수있게 말해주세요"),
            self._tg(3, "그게 무슨 뜻이야?"),
            self._tg(4, "현재 진행상황 알려줘"),
        ]
        for text in answers:
            self.assertNotIn(_UNRELATED_TEST_SYMBOL, text)
            self.assertNotIn("삼성전자", text)
            self.assertNotIn("005930", text)


class MissionWithNoActiveCandidate(_Base):
    WITH_ACTIVE = False

    def test_blocked_no_active_candidate_status_is_read_only_and_natural(self) -> None:
        before = _mission_snapshot(self.conn)
        resp = self._web("단타 연구는 잘 되고 있나요?", session_ref="noactive")
        self.assertIn(resp["route"], _MISSION_AWARE_ROUTES)
        self._assert_safe(resp)
        self.assertNotIn("strategy_hypothesis_space_exhausted", resp["text"])
        self.assertEqual(before, _mission_snapshot(self.conn))


if __name__ == "__main__":
    unittest.main()
