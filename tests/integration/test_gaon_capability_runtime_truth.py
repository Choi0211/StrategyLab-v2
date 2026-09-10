"""Gaon Capability & Need Registry: Runtime Truth & Blocker Diagnosis
(roadmap item #215) - end-to-end on both the Web and the Telegram
conversation paths.

Production topology for natural conversation is
``Gaon VPS -> Tailscale -> user PC -> Ollama/qwen3:8b``. When that PC is off,
``GENERAL_CONVERSATION`` is still *configured* AVAILABLE but genuinely
unusable. These tests pin the honest behaviour:

* an identity / small-talk turn gets a short, honest "the conversation model
  is offline, server features still work" reply - never the legacy
  "요청을 이해하지 못했습니다" fallback and never a stale research subject;
* mission / strategy reads and the deterministic safety gate are completely
  unaffected by provider health;
* the capability ("무엇을 할 수 있나요?") answer reflects the runtime truth;
* a multi-intent turn is partially fulfilled - the offline segment is
  explained, the authoritative segment is still answered.
"""

from __future__ import annotations

import json
import sqlite3
import unittest

from gaon.knowledge.research_mission import MissionStatus, extract_or_update_mission
from gaon.runtime import llm_conversation
from gaon.runtime.assistant_provider import ProviderTimeoutError, ProviderUnavailableError
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import (
    LLMConversationRequest,
    LLMConversationSession,
    SQLiteConversationRepository,
)
from gaon.runtime.migrations import migrate
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-09-10T09:30:00Z"
SEED_AT = "2026-09-10T09:29:00Z"

_COMPLAINT = "말씀해 주신 불편을 확인했습니다"
_LEGACY_FALLBACK = "이해하지 못했습니다"
_RUNTIME_ROUTE = "conversation_runtime_unavailable"
_MISSION_INVARIANT_FIELDS = (
    "mission_id",
    "market",
    "status",
    "target_promotion_ready_candidates",
    "cycles_completed",
    "blocked_reason",
)
_RESEARCH_TOOLS = (
    "autonomous_learning_research",
    "autonomous_research_cycle",
    "multi_symbol_research",
    "krx_real_research",
    "research_retest",
)


class _Provider:
    """Stands in for the production Ollama model.

    ``mode``: ``ok`` returns text, ``unreachable`` raises
    :class:`ProviderUnavailableError` (PC/Ollama off, connection refused),
    ``timeout`` raises :class:`ProviderTimeoutError`.
    """

    def __init__(self, *, mode: str = "unreachable") -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self._mode = mode

    def respond(self, request):  # noqa: ANN001 - test double
        self.calls += 1
        self.prompts.append(request.prompt or request.text)
        if self._mode == "timeout":
            raise ProviderTimeoutError("local model timed out")
        if self._mode == "unreachable":
            raise ProviderUnavailableError("assistant provider request failed")
        return llm_conversation.AssistantProviderResponse(
            text="네 영하님, 저는 영하님의 AI 연구 파트너 가온입니다.",
            provider_name="openai-compatible",
        )


def _blocked_daytrade_mission() -> dict:
    mission = extract_or_update_mission(
        "국내 주식 전체(코스피+코스닥)를 대상으로 수익과 안전성을 개선하는 단타 전략을 "
        "연구해주세요. 승격 가능한 후보 3개까지.",
        existing=None,
        now=SEED_AT,
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


def _stale_000370_context() -> dict:
    grounded = "영하님, 000370 전략을 다시 연구했습니다.\n- 자율 연구 사이클을 1회 수행했습니다."
    payload = {"symbol": "000370", "mode": "research", "promotion_status": "not_ready"}
    return {
        "last_intent": "autonomous_learning_v2",
        "last_symbols": ["000370"],
        "last_result_kind": "autonomous_learning_v2",
        "last_rendered_result": grounded,
        "last_payloads": [payload],
        "last_summary": grounded,
        "last_detail_payload": payload,
        "last_source": "autonomous_learning_research",
        "last_fixture_backed": False,
        "last_quality_status": "ok",
        "detail_level": "summary",
        "created_at": "2026-09-08T00:00:00Z",
        "updated_at": "2026-09-08T00:00:00Z",
    }


class _RuntimeTruthMixin:
    transport: str

    # -- implemented by the concrete transport subclasses --------------
    def _send(self, text: str) -> dict:
        raise NotImplementedError

    def _connection(self) -> sqlite3.Connection:
        raise NotImplementedError

    def _session_id(self) -> str:
        raise NotImplementedError

    # -- shared fixture / assertions ---------------------------------
    def _seed_mission(self, *, with_stale_context: bool = False) -> None:
        connection = self._connection()
        repo = SQLiteConversationRepository(connection)
        session_id = self._session_id()
        try:
            session = repo.get_session(session_id)
            metadata = dict(session.metadata)
            created_at = session.created_at
            user_ref = session.user_ref
        except KeyError:
            metadata = {"owner": "gaon"}
            created_at = SEED_AT
            user_ref = "seed-user"
            repo.upsert_session(
                LLMConversationSession(
                    session_id, user_ref, self.transport, "active", created_at, SEED_AT, metadata
                )
            )
        mvp: dict = {"schema_version": 1, "research_mission": _blocked_daytrade_mission()}
        if with_stale_context:
            mvp["last_research_context"] = _stale_000370_context()
        metadata["conversation_mvp"] = mvp
        repo.upsert_session(
            LLMConversationSession(
                session_id, user_ref, self.transport, "active", created_at, SEED_AT, metadata
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

    def _assert_no_stale_symbol(self, payload: dict, ctx: str = "") -> None:
        self.assertNotIn("000370", payload["text"], ctx)
        self.assertNotIn("005930", payload["text"], ctx)
        self.assertNotIn("전략을 다시 연구했습니다", payload["text"], ctx)

    # ================================================================
    # identity / small talk while the model is offline
    # ================================================================
    def test_identity_question_offline_is_honest_not_a_comprehension_failure(self) -> None:
        self._seed_mission()
        payload = self._send("이름이 뭐예요?")
        self.assertEqual(payload["route"], _RUNTIME_ROUTE)
        self.assertNotIn(_COMPLAINT, payload["text"])
        self.assertNotIn(_LEGACY_FALLBACK, payload["text"])
        self.assertIn("연결할 수 없", payload["text"])
        self.assertIn("서버 기능", payload["text"])
        self.assertEqual(tuple(payload["tool_calls"]), ())

    def test_identity_question_offline_never_returns_a_stale_symbol_result(self) -> None:
        self._seed_mission(with_stale_context=True)
        before = self._mission_snapshot()
        payload = self._send("이름이 뭐예요?")
        self._assert_no_stale_symbol(payload, "identity offline")
        self.assertEqual(payload["route"], _RUNTIME_ROUTE)
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    def test_timeout_offline_reply_points_at_retry(self) -> None:
        self._provider._mode = "timeout"
        self._seed_mission()
        payload = self._send("재밌는 이야기 해줘")
        self.assertEqual(payload["route"], _RUNTIME_ROUTE)
        self.assertRegex(payload["text"], r"(지연|다시 시도)")
        self.assertNotIn(_COMPLAINT, payload["text"])

    def test_healthy_provider_identity_still_reaches_the_model(self) -> None:
        self._provider._mode = "ok"
        self._seed_mission()
        payload = self._send("이름이 뭐예요?")
        self.assertNotEqual(payload["route"], _RUNTIME_ROUTE)
        self.assertGreaterEqual(self._provider.calls, 1)
        self.assertIn("가온", payload["text"])

    # ================================================================
    # authoritative reads are unaffected by provider health
    # ================================================================
    def test_mission_status_read_survives_llm_offline(self) -> None:
        self._seed_mission()
        before = self._mission_snapshot()
        payload = self._send("단타 전략 연구는 지금 어떻게 되고 있어요?")
        self.assertNotEqual(payload["route"], _RUNTIME_ROUTE)
        self.assertIn("단타", payload["text"])
        self.assertEqual(tuple(payload["tool_calls"]), ())
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    def test_blocker_question_survives_llm_offline_with_authoritative_answer(self) -> None:
        self._seed_mission(with_stale_context=True)
        before = self._mission_snapshot()
        payload = self._send("단타 연구 왜 멈췄어요?")
        self.assertNotEqual(payload["route"], _RUNTIME_ROUTE)
        self.assertIn("단타", payload["text"])
        self._assert_no_stale_symbol(payload, "blocker offline")
        self.assertEqual(tuple(payload["tool_calls"]), ())
        self.assertEqual(self._mission_snapshot(), before)

    # ================================================================
    # capability answer reflects runtime truth
    # ================================================================
    def test_capability_question_reflects_runtime_truth_when_offline(self) -> None:
        self._seed_mission()
        # first turn establishes the offline signal, second turn asks help
        self._send("이름이 뭐예요?")
        payload = self._send("무엇을 할 수 있나요?")
        self.assertEqual(payload["route"], "conversation_mvp_help")
        self.assertIn("제한", payload["text"])
        self.assertIn("서버 기능", payload["text"])
        # still lists the real server-native capabilities
        self.assertIn("연구 미션", payload["text"])

    def test_capability_question_has_no_runtime_caveat_when_state_unknown(self) -> None:
        self._provider._mode = "ok"
        self._seed_mission()
        payload = self._send("무엇을 할 수 있나요?")
        self.assertEqual(payload["route"], "conversation_mvp_help")
        # no provider failure recorded -> no guessed caveat
        self.assertNotIn("대화용 AI 모델에 연결할 수 없", payload["text"])

    # ================================================================
    # capability-limitation lanes are unchanged by provider health
    # ================================================================
    def test_url_request_offline_still_uses_the_url_limitation_lane(self) -> None:
        self._seed_mission()
        payload = self._send("https://www.instagram.com/p/DcHnMH-kzA5/\n이건 어때요?")
        self.assertEqual(payload["route"], "conversation_capability_limited_url")
        self.assertIn("링크를 직접 열어", payload["text"])

    def test_current_info_request_offline_still_uses_the_current_info_lane(self) -> None:
        self._seed_mission()
        payload = self._send("오늘 날씨는 어때요?")
        self.assertEqual(payload["route"], "conversation_capability_limited_current_info")
        self.assertIn("실시간 정보", payload["text"])

    # ================================================================
    # multi-intent partial fulfilment
    # ================================================================
    def test_multi_intent_offline_explains_first_answers_second(self) -> None:
        self._seed_mission(with_stale_context=True)
        before = self._mission_snapshot()
        payload = self._send("이름이 뭐예요?\n\n단타 전략 연구는 왜 멈췄어요?")
        self.assertEqual(payload["route"], "conversation_multi_intent")
        self.assertRegex(payload["text"], r"(연결할 수 없|대화용 AI 모델)")
        self.assertIn("단타", payload["text"])
        self._assert_no_stale_symbol(payload, "multi-intent offline")
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)

    # ================================================================
    # the deterministic safety gate does not consult the provider at all
    # ================================================================
    def test_forbidden_request_offline_is_still_gated_deterministically(self) -> None:
        self._seed_mission()
        payload = self._send("삼성전자 100주 매수 주문 넣고 승인까지 해줘")
        self.assertNotEqual(payload["route"], _RUNTIME_ROUTE)
        self.assertEqual(self._provider.calls, 0)
        self.assertNotIn("주문을 실행했습니다", payload["text"])
        self.assertNotIn("승인했습니다", payload["text"])

    def test_no_mission_mutation_from_offline_capability_queries(self) -> None:
        self._seed_mission(with_stale_context=True)
        before = self._mission_snapshot()
        for text in ("이름이 뭐예요?", "무엇을 할 수 있나요?", "오늘 날씨는 어때요?", "재밌는 이야기 해줘"):
            self._send(text)
        self.assertEqual(self._research_tool_audit_count(), 0)
        self.assertEqual(self._mission_snapshot(), before)


class GaonTelegramRuntimeTruthTests(_RuntimeTruthMixin, unittest.TestCase):
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
        return "telegram:920"

    def _send(self, text: str) -> dict:
        self._mid += 1
        response = self._agent._brain.respond(
            LLMConversationRequest(
                session_id=self._session_id(),
                user_ref="telegram-user:920",
                source="telegram",
                text=text,
                received_at=NOW,
                message_id=f"telegram:920:{self._mid}",
            )
        )
        return {
            "text": response.text,
            "route": response.route,
            "tool_calls": tuple(response.tool_calls),
        }


class GaonWebRuntimeTruthTests(_RuntimeTruthMixin, unittest.TestCase):
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
        return "web:s920"

    def _send(self, text: str) -> dict:
        payload = dict(
            self._adapter.handle(
                message=text,
                session_ref="s920",
                user_ref="u920",
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
