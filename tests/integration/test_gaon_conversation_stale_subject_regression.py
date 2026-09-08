"""#214 post-deploy Conversation-Integrity regression.

Production E2E after PR #214 showed a general-knowledge question
("우주는 왜 어두운가요?") answered by re-rendering a STALE
``ConversationalMVPContext`` - an earlier background autonomous
``autonomous_learning_v2`` research on symbol 000370 - so Gaon replied
"영하님, 000370 전략을 다시 연구했습니다 ..." as if it had just re-run
research, on the durable KR/단타 ResearchMission's own turn. No tool
actually ran and the mission was not mutated, but the answer read as a
fresh research action bound to a stale symbol subject - a Conversation
Integrity violation.

Root cause: in ``LLMConversationBrain._try_conversational_mvp`` the
reasoning-followup branch consumed the stored ``ConversationalMVPContext``
for any EXPLAIN/SIMPLIFY-intent turn, with no check that the turn is
actually a follow-up to that stored result. ``classify_conversational_route``
tags a bare "왜" question as ``EXPLAIN_PREVIOUS_RESULT``; the PR #213 guard
that defers such a non-back-referencing "why" to the LLM lived only inside
the ``context is None`` branch, so a stale context bypassed it entirely.

Fix (deterministic, no new capability, safety boundaries unchanged):

* A read-only turn that is a complete standalone question with its own
  non-research subject, does not point back at an earlier answer, and names
  no research/mission subject is routed LLM-first - never resolved against a
  persisted mission or a stored context.
* A read-only research/mission question ("단타 연구 왜 멈췄어요?") whose
  stored context is stale (>2h old - an earlier session / a background run)
  is answered from the ResearchMission's authoritative persisted state, not
  the stale context.
* Read-only follow-up continuity ("왜 멈췄어요?" -> "쉽게 말하면?",
  "거래비용에는 왜 약해?") is unchanged.

Both the Telegram and the Web adapters share ``LLMConversationBrain`` /
``_try_conversational_mvp``; every scenario below is exercised on both.
"""

from __future__ import annotations

import json
import sqlite3
import unittest

from gaon.knowledge.research_mission import MissionStatus, extract_or_update_mission
from gaon.runtime import llm_conversation
from gaon.runtime.assistant_provider import AssistantProviderResponse, ProviderTimeoutError
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import (
    LLMConversationRequest,
    LLMConversationSession,
    SQLiteConversationRepository,
)
from gaon.runtime.migrations import migrate
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-09-08T09:30:00Z"
STALE_AT = "2026-09-07T00:00:00Z"  # >2h before NOW -> stale context

_COMPLAINT = "말씀해 주신 불편을 확인했습니다"
_LEGACY_FALLBACK = "이해하지 못했습니다"
_RESEARCH_TOOLS = (
    "autonomous_learning_research",
    "autonomous_research_cycle",
    "multi_symbol_research",
    "krx_real_research",
    "research_retest",
)
_MISSION_INVARIANT_FIELDS = (
    "mission_id",
    "market",
    "universe_scope",
    "status",
    "target_promotion_ready_candidates",
    "cycles_completed",
    "blocked_reason",
)


def _stale_000370_research_context() -> dict:
    grounded = "영하님, 000370 전략을 다시 연구했습니다.\n- 자율 연구 사이클을 1회 수행했습니다."
    detail_payload = {
        "symbol": "000370",
        "mode": "research",
        "promotion_status": "not_ready",
        "human_gate_status": "not_requested",
        "autonomous_learning_v2": {
            "external_research_state": "used",
            "promotion_candidate_context": {"candidate_id": "KR-ST-000370-1"},
        },
        "assessment": {"status": "검증 계속 필요"},
        "plan": {"steps": [{"name": "oos"}]},
        "critic_report": {"findings": [{"k": "v"}], "proposals": [{"k": "v"}]},
        "learning_report": {"stored_records": [{"k": "v"}]},
        "progression": {"progression_state": "in_progress"},
    }
    return {
        "last_intent": "autonomous_learning_v2",
        "last_symbols": ["000370"],
        "last_result_kind": "autonomous_learning_v2",
        "last_research_result_ids": ["res-000370-1"],
        "last_rendered_result": grounded,
        "last_payloads": [detail_payload],
        "last_structured_results": [detail_payload],
        "last_summary": grounded,
        "last_detail_payload": detail_payload,
        "last_source": "autonomous_learning_research",
        "last_fixture_backed": False,
        "last_quality_status": "ok",
        "detail_level": "summary",
        "created_at": STALE_AT,
        "updated_at": STALE_AT,
    }


def _blocked_daytrade_mission() -> dict:
    mission = extract_or_update_mission(
        "국내 주식 전체(코스피+코스닥)를 대상으로 수익과 안전성을 개선하는 단타 전략을 "
        "연구해주세요. 승격 가능한 후보 3개까지.",
        existing=None,
        now=STALE_AT,
    )
    mission = mission.__class__.from_json(
        {
            **mission.to_json(),
            "status": MissionStatus.BLOCKED.value,
            "blocked_reason": (
                "strategy_hypothesis_space_exhausted: bounded declarative strategy "
                "expansion budget exhausted"
            ),
        }
    )
    return mission.to_json()


class _Provider:
    """Stands in for the offline production Ollama model."""

    def __init__(self, *, raise_timeout: bool = False, text: str = "네 영하님, 저는 영하님의 AI 연구 파트너 가온입니다.") -> None:
        self.calls = 0
        self._raise_timeout = raise_timeout
        self._text = text

    def respond(self, request):  # noqa: ANN001 - test double
        self.calls += 1
        if self._raise_timeout:
            raise ProviderTimeoutError("local model timed out")
        return AssistantProviderResponse(text=self._text, provider_name="openai-compatible")


class _StaleSubjectRegressionMixin:
    """One scenario set, run against both transports via ``_send`` /
    ``_seed`` / ``_connection`` supplied by the concrete subclasses."""

    transport: str

    # -- helpers the subclasses implement -----------------------------
    def _send(self, text: str) -> dict:  # -> {"text", "route", "tool_calls"}
        raise NotImplementedError

    def _connection(self) -> sqlite3.Connection:
        raise NotImplementedError

    def _session_id(self) -> str:
        raise NotImplementedError

    # -- shared fixture seeding --------------------------------------
    def _seed_stale_subject_and_mission(self, *, symbols=("000370",)) -> None:
        connection = self._connection()
        repo = SQLiteConversationRepository(connection)
        session_id = self._session_id()
        try:
            session = repo.get_session(session_id)
            metadata = dict(session.metadata)
        except KeyError:
            session = LLMConversationSession(
                session_id, "seed-user", self.transport, "active", STALE_AT, STALE_AT, {"owner": "gaon"}
            )
            repo.upsert_session(session)
            metadata = {"owner": "gaon"}
        ctx = _stale_000370_research_context()
        ctx["last_symbols"] = list(symbols)
        ctx["last_detail_payload"] = {**ctx["last_detail_payload"], "symbol": symbols[0]}
        metadata["conversation_mvp"] = {
            "schema_version": 1,
            "last_research_context": ctx,
            "research_mission": _blocked_daytrade_mission(),
        }
        repo.upsert_session(
            LLMConversationSession(
                session_id, session.user_ref, self.transport, "active", session.created_at, STALE_AT, metadata
            )
        )

    def _mission_snapshot(self) -> dict:
        row = self._connection().execute(
            "SELECT metadata_json FROM conversation_sessions WHERE session_id = ?",
            (self._session_id(),),
        ).fetchone()
        mission = json.loads(row[0])["conversation_mvp"]["research_mission"]
        return {field: mission.get(field) for field in _MISSION_INVARIANT_FIELDS} | {
            "candidate_count": len(mission.get("candidates", []))
        }

    def _research_tool_audit_count(self) -> int:
        placeholders = ",".join("?" * len(_RESEARCH_TOOLS))
        return self._connection().execute(
            f"SELECT COUNT(*) FROM llm_tool_audit WHERE tool_name IN ({placeholders})",
            _RESEARCH_TOOLS,
        ).fetchone()[0]

    def _assert_general_conversation(self, payload: dict, text: str) -> None:
        self.assertNotIn("000370", payload["text"], text)
        self.assertNotIn("005930", payload["text"], text)
        self.assertNotIn("전략을 다시 연구했습니다", payload["text"], text)
        self.assertNotIn(_COMPLAINT, payload["text"], text)
        self.assertNotIn(_LEGACY_FALLBACK, payload["text"], text)
        self.assertEqual(tuple(payload["tool_calls"]), (), text)
        self.assertNotIn("autonomous", payload["route"], text)
        # the real safety property: no research tool ran for this turn
        self.assertEqual(self._research_tool_audit_count(), 0, text)

    # ================================================================
    # spec 3 / CRITICAL: a bare knowledge question with a stale 000370
    # autonomous context must never re-render it as a research action.
    # ================================================================
    def test_universe_question_with_stale_000370_context_is_general_not_research(self) -> None:
        self._seed_stale_subject_and_mission(symbols=("000370",))
        before = self._mission_snapshot()

        payload = self._send("우주는 왜 어두운가요?")

        self._assert_general_conversation(payload, "우주는 왜 어두운가요?")
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before, "durable ResearchMission must be invariant")

    def test_universe_question_with_stale_005930_context_is_general_not_research(self) -> None:
        self._seed_stale_subject_and_mission(symbols=("005930",))
        before = self._mission_snapshot()

        payload = self._send("우주는 왜 어두운가요?")

        self._assert_general_conversation(payload, "우주는 왜 어두운가요?")
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    def test_typo_variant_universe_question_is_also_general(self) -> None:
        self._seed_stale_subject_and_mission()
        payload = self._send("우주는 왜 어두워요")
        self._assert_general_conversation(payload, "우주는 왜 어두워요")
        self.assertEqual(self._research_tool_audit_count(), 0)

    # -- spec 1 -----------------------------------------------------
    def test_greeting_is_general(self) -> None:
        self._seed_stale_subject_and_mission()
        payload = self._send("안녕하세요")
        self.assertIn("가온", payload["text"])
        self.assertEqual(tuple(payload["tool_calls"]), ())
        self.assertEqual(self._research_tool_audit_count(), 0)

    # -- spec 2 ---------------------------------------------------
    def test_identity_question_reaches_the_model_no_legacy_fallback(self) -> None:
        self._seed_stale_subject_and_mission()
        before = self._mission_snapshot()
        payload = self._send("이름이 뭐예요?")
        self._assert_general_conversation(payload, "이름이 뭐예요?")
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    def test_identity_question_alternate_spelling_reaches_the_model(self) -> None:
        self._seed_stale_subject_and_mission()
        payload = self._send("이름이 뭐에요?")
        self._assert_general_conversation(payload, "이름이 뭐에요?")

    # -- spec 4 -------------------------------------------------
    def test_smalltalk_story_request_is_general_not_research(self) -> None:
        self._seed_stale_subject_and_mission()
        before = self._mission_snapshot()
        payload = self._send("재밌는 이야기 하나 해줘")
        self._assert_general_conversation(payload, "재밌는 이야기 하나 해줘")
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    # -- spec 5 + 6: read-only mission blocker continuity ---------
    def test_daytrade_blocker_question_then_simplify_stays_read_only_mission(self) -> None:
        self._seed_stale_subject_and_mission()
        before = self._mission_snapshot()

        status = self._send("단타 전략 연구는 지금 어떻게 되고 있어요?")
        self.assertIn("단타", status["text"])
        self.assertEqual(tuple(status["tool_calls"]), ())

        why = self._send("왜 멈췄어요?")
        self.assertIn("멈춘", why["text"])
        self.assertNotIn("000370", why["text"])
        self.assertEqual(tuple(why["tool_calls"]), ())

        simpler = self._send("쉽게 말하면?")
        self.assertNotIn("000370", simpler["text"])
        self.assertNotIn("전략을 다시 연구했습니다", simpler["text"])
        self.assertEqual(tuple(simpler["tool_calls"]), ())

        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    def test_standalone_daytrade_blocker_question_reads_mission_not_stale_context(self) -> None:
        self._seed_stale_subject_and_mission(symbols=("000370",))
        before = self._mission_snapshot()

        payload = self._send("단타 연구 왜 멈췄어요?")

        self.assertNotIn("000370", payload["text"])
        self.assertNotIn("전략을 다시 연구했습니다", payload["text"])
        self.assertIn("단타", payload["text"])
        self.assertEqual(tuple(payload["tool_calls"]), ())
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    # -- spec 7: topic switch back to general after mission talk -----
    def test_switch_back_to_general_after_mission_talk(self) -> None:
        self._seed_stale_subject_and_mission()
        before = self._mission_snapshot()

        self._send("단타 전략 연구는 지금 어떻게 되고 있어요?")
        self._send("왜 멈췄어요?")
        payload = self._send("그런데 우주는 왜 어두워?")

        self._assert_general_conversation(payload, "그런데 우주는 왜 어두워?")
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    # -- spec 8: return to the mission topic - never a stale symbol /
    # research action (answered conversationally; see module note). -----
    def test_return_to_daytrade_topic_never_leaks_stale_symbol_or_runs_research(self) -> None:
        self._seed_stale_subject_and_mission()
        before = self._mission_snapshot()

        self._send("단타 전략 연구는 지금 어떻게 되고 있어요?")
        self._send("왜 멈췄어요?")
        payload = self._send("다시 단타 얘기로 돌아가서 가장 큰 문제는 뭐예요?")

        self.assertNotIn("000370", payload["text"])
        self.assertNotIn("전략을 다시 연구했습니다", payload["text"])
        self.assertEqual(tuple(payload["tool_calls"]), ())
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    # -- spec 9: multi-intent -------------------------------------
    def test_multi_intent_identity_plus_mission_answers_both_no_research(self) -> None:
        self._seed_stale_subject_and_mission()
        before = self._mission_snapshot()

        payload = self._send(
            "이름이 뭐예요?\n\n그리고 단타 전략이 승격될 정도가 되려면 지금 뭐가 더 필요해요?"
        )

        self.assertEqual(payload["route"], "conversation_multi_intent")
        self.assertIn("가온", payload["text"])          # identity segment
        self.assertIn("단타", payload["text"])          # mission segment
        self.assertNotIn("000370", payload["text"])
        self.assertNotIn("전략을 다시 연구했습니다", payload["text"])
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    # -- spec 10 / 11: honest capability limits (unchanged by fix) ---
    def test_current_info_request_is_truthfully_unavailable(self) -> None:
        self._seed_stale_subject_and_mission()
        payload = self._send("오늘 날씨는 어때요?")
        self.assertEqual(payload["route"], "conversation_capability_limited_current_info")
        self.assertIn("실시간 정보", payload["text"])
        self.assertEqual(tuple(payload["tool_calls"]), ())

    def test_url_message_is_truthfully_limited(self) -> None:
        self._seed_stale_subject_and_mission()
        payload = self._send("https://www.instagram.com/p/DcHnMH-kzA5/\n이건 어때요?")
        self.assertEqual(payload["route"], "conversation_capability_limited_url")
        self.assertNotIn("확인했습니다", payload["text"])
        self.assertNotIn("000370", payload["text"])


class GaonTelegramStaleSubjectRegressionTests(_StaleSubjectRegressionMixin, unittest.TestCase):
    transport = "telegram"

    def setUp(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self.addCleanup(self._conn.close)
        migrate(self._conn)
        self._provider = _Provider()
        self._agent = TelegramConversationAgent(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            self._conn,
            assistant_provider=self._provider,
        )
        self._mid = 0

    def _connection(self) -> sqlite3.Connection:
        return self._conn

    def _session_id(self) -> str:
        return "telegram:900"

    def _send(self, text: str) -> dict:
        self._mid += 1
        # ``TelegramConversationAgent.handle`` drops ``tool_calls`` from its
        # ``ConversationResponse``; go through the shared brain directly so
        # the regression can assert on the real executed-tool list.
        response = self._agent._brain.respond(
            LLMConversationRequest(
                session_id=self._session_id(),
                user_ref="telegram-user:900",
                source="telegram",
                text=text,
                received_at=NOW,
                message_id=f"telegram:900:{self._mid}",
            )
        )
        return {
            "text": response.text,
            "route": response.route,
            "tool_calls": tuple(response.tool_calls),
        }


class GaonWebStaleSubjectRegressionTests(_StaleSubjectRegressionMixin, unittest.TestCase):
    transport = "web"

    def setUp(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self.addCleanup(self._conn.close)
        migrate(self._conn)
        self._provider = _Provider()
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: self._provider
        self.addCleanup(setattr, llm_conversation, "build_assistant_provider", original)
        self._adapter = GaonWebChatAdapter(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            self._conn,
        )

    def _connection(self) -> sqlite3.Connection:
        return self._conn

    def _session_id(self) -> str:
        return "web:s900"

    def _send(self, text: str) -> dict:
        payload = dict(
            self._adapter.handle(
                message=text,
                session_ref="s900",
                user_ref="u900",
                read_only=False,
                received_at=NOW,
            )
        )
        return {
            "text": payload["text"],
            "route": payload["route"],
            "tool_calls": tuple(payload.get("tool_calls", ())),
        }


if __name__ == "__main__":
    unittest.main()
