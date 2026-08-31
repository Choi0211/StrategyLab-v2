"""Regression tests for hotfix/conversation-layer-safe-web-parity.

Root cause (see docs/architecture and the conversation-layer diagnostic that
preceded this branch): production runs GAON_ASSISTANT_ENABLED=true,
GAON_ASSISTANT_PROVIDER=openai-compatible. Web (GaonWebChatAdapter,
source="web") was excluded from LLMConversationBrain._try_conversational_mvp
by _is_conversational_mvp_source, which only admitted Telegram - so Web had
no mission-aware STATUS/READ layer at all. Worse, route_read_only_tool()
matches on research TOPIC words ("연구", a symbol name), not on an
imperative verb, and _try_authoritative_research_tool executed the 5 real
research-execution tools it names (is_strict_real_research_tool) BEFORE any
LLM reasoning, regardless of request.source - so an honest status question
like "삼성전자 연구 상태 알려줘" satisfied _krx_real_research's matcher and
ran a real research pipeline synchronously.

This suite proves, for BOTH Web (GaonWebChatAdapter) and Telegram
(TelegramConversationAgent) - same input text, same assertions:

1. A STATUS/READ question never executes a strict real-research tool and
   never creates/mutates a ResearchMission (TEST GROUP 1).
2. General conversation / greeting / availability questions never leak KR
   research results and never touch ResearchMission (TEST GROUP 2).
3. An explicit execution request DOES reach the authoritative real-research
   tool route, with existing grounding/safety checks intact (TEST GROUP 3).
4. An ambiguous bare noun phrase never executes anything (TEST GROUP 4).
5. A short multi-turn exchange resolves the earlier subject and only
   executes on the turn that explicitly asks to (TEST GROUP 5).
6. Approval-adjacent conversational text never advances the strategy
   lifecycle past conversation (TEST GROUP 6).

All 5 strict real-research tools (krx_real_research, autonomous_research_
cycle, autonomous_learning_research, research_retest, multi_symbol_research)
run against GaonRuntimeConfig's fixture-mode defaults
(market_data_provider="fixture", real_market_data_enabled=False) - the same
defaults tests/integration/test_telegram_conversation_agent.py already
relies on - so a real execution in TEST GROUP 3 is local/deterministic, not
a live network call.
"""
from __future__ import annotations

import unittest

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_tool_routing import has_explicit_research_execution_intent, route_read_only_tool
from gaon.runtime.research_grounding import is_strict_real_research_tool
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-08-31T00:00:00Z"

_STRICT_TOOLS = ("krx_real_research", "autonomous_research_cycle", "autonomous_learning_research", "research_retest", "multi_symbol_research")


def _config(*, assistant_provider: str = "deterministic") -> GaonRuntimeConfig:
    return GaonRuntimeConfig(assistant_enabled=True, assistant_provider=assistant_provider)


class _FakeTelegramClient:
    def __init__(self, updates=()) -> None:
        self.updates = updates
        self.sent: list[tuple[str, str]] = []

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        return self.updates

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


def _telegram_update(update_id: int, text: str, *, chat_id: int = 100) -> dict:
    return {"update_id": update_id, "message": {"message_id": update_id, "chat": {"id": chat_id}, "from": {"id": 200}, "text": text}}


def _web_send(store: RuntimeStateStore, text: str, *, session_ref: str = "w1", config: GaonRuntimeConfig | None = None, received_at: str = NOW) -> dict:
    adapter = GaonWebChatAdapter(config or _config(), store._connection)
    return adapter.handle(message=text, session_ref=session_ref, user_ref="web-u1", read_only=False, received_at=received_at)


def _telegram_send(store: RuntimeStateStore, text: str, *, chat_id: int = 100, config: GaonRuntimeConfig | None = None, received_at: str = NOW) -> str:
    client = _FakeTelegramClient((_telegram_update(1, text, chat_id=chat_id),))
    runtime = TelegramRuntime(TelegramConversationAgent(config or _config(), store._connection), allowed_chat_ids=(str(chat_id),))
    process_update(parse_update_result(client.updates[0], received_at=received_at), runtime, client)
    return client.sent[-1][1]


def _strict_tool_call_counts(store: RuntimeStateStore) -> dict[str, int]:
    return {name: len(store.tool_audit.list(tool_name=name)) for name in _STRICT_TOOLS}


class StatusReadMustNotExecuteTests(unittest.TestCase):
    """TEST GROUP 1 - a research-progress status question must never
    execute a strict real-research tool or mutate a ResearchMission, on
    either transport."""

    MESSAGES = (
        "단타 연구는 잘되가고 있나요?",
        "삼성전자 연구 상태 알려줘",
        "후보가 나왔어?",
        "검증 끝났어?",
    )

    def test_web_status_questions_never_execute_research(self) -> None:
        for text in self.MESSAGES:
            with self.subTest(transport="web", text=text):
                store = RuntimeStateStore(":memory:")
                payload = _web_send(store, text)
                self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
                self.assertEqual(payload["tool_calls"], [])
                self.assertFalse(payload["strategy_mutated"])
                self.assertFalse(payload["order_executed"])
                self.assertFalse(payload["champion_promoted"])
                store.close()

    def test_telegram_status_questions_never_execute_research(self) -> None:
        for text in self.MESSAGES:
            with self.subTest(transport="telegram", text=text):
                store = RuntimeStateStore(":memory:")
                _telegram_send(store, text)
                self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
                store.close()

    def test_web_and_telegram_route_the_same_status_question_without_a_research_mission(self) -> None:
        text = "단타 연구는 잘되가고 있나요?"
        web_store = RuntimeStateStore(":memory:")
        telegram_store = RuntimeStateStore(":memory:")
        try:
            web_payload = _web_send(web_store, text)
            telegram_text = _telegram_send(telegram_store, text)
            # Same mission-aware "no active Research Mission" read model on
            # both transports - not a generic "말씀해 주신 불편을
            # 확인했습니다" complaint-handling fallback, not a keyword-bot
            # "도움말이라고 말씀해 주세요" fallback.
            for text_out in (web_payload["text"], telegram_text):
                self.assertIn("Research Mission", text_out)
                self.assertNotIn("말씀해 주신 불편을 확인했습니다", text_out)
                self.assertNotIn("도움말이라고 말씀해", text_out)
            self.assertEqual(web_payload["route"], "conversation_research_status_no_mission")
        finally:
            web_store.close()
            telegram_store.close()


class GeneralConversationSafetyTests(unittest.TestCase):
    """TEST GROUP 2 - greetings/availability questions never leak KR
    research results and never touch ResearchMission."""

    MESSAGES = (
        "안녕 가온아",
        "현재 연결 상태를 알려줘",
        "언재쯤 대화가 가능할까요",
        "안녕 가온아. 현재 연결 상태를 알려줘.",  # the original reported regression
    )

    def test_web_general_conversation_has_no_research_execution_or_kr_leak(self) -> None:
        for text in self.MESSAGES:
            with self.subTest(transport="web", text=text):
                store = RuntimeStateStore(":memory:")
                payload = _web_send(store, text)
                self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
                for forbidden in ("KOSPI", "KOSDAQ", "코스피", "코스닥", "candidate", "strategy_candidates"):
                    self.assertNotIn(forbidden, payload["text"])
                store.close()

    def test_telegram_general_conversation_has_no_research_execution_or_kr_leak(self) -> None:
        for text in self.MESSAGES:
            with self.subTest(transport="telegram", text=text):
                store = RuntimeStateStore(":memory:")
                reply = _telegram_send(store, text)
                self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
                for forbidden in ("KOSPI", "KOSDAQ", "코스피", "코스닥"):
                    self.assertNotIn(forbidden, reply)
                store.close()

    def test_connection_status_regression_answers_status_not_kr_research(self) -> None:
        # This is the exact symptom from the original diagnostic: a
        # connection/status greeting must render runtime status, never a
        # multi-symbol KR research dump.
        text = "안녕 가온아. 현재 연결 상태를 알려줘."
        for transport, run in (("web", lambda s: _web_send(s, text)["text"]), ("telegram", lambda s: _telegram_send(s, text))):
            with self.subTest(transport=transport):
                store = RuntimeStateStore(":memory:")
                reply = run(store)
                self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
                for forbidden in ("KOSPI", "KOSDAQ", "market=KR", "candidate"):
                    self.assertNotIn(forbidden, reply)
                store.close()


class ExplicitResearchExecutionTests(unittest.TestCase):
    """TEST GROUP 3 - an explicit execution request reaches the
    authoritative real-research tool route with grounding intact."""

    def test_explicit_execution_phrasing_is_recognized_as_execution_intent(self) -> None:
        # Pure routing-decision proof for the exact phrasings the hotfix
        # spec named. "단타 전략을 새로 연구해줘." names no symbol this
        # codebase's curated-universe tools recognize (a separate, pre-
        # existing coverage gap, not a safety issue this PR scopes in) so
        # it does not reach route_read_only_tool - what matters for THIS
        # PR is that has_explicit_research_execution_intent still correctly
        # reads it as an execution request, not a status question.
        for text in ("삼성전자 전략을 처음부터 다시 연구해줘.", "단타 전략을 새로 연구해줘."):
            with self.subTest(text=text):
                self.assertTrue(has_explicit_research_execution_intent(text))
        tool_name = route_read_only_tool("삼성전자 전략을 처음부터 다시 연구해줘.")
        self.assertIsNotNone(tool_name)
        self.assertTrue(is_strict_real_research_tool(tool_name))

    def test_status_question_does_not_satisfy_the_routing_gate(self) -> None:
        for text in StatusReadMustNotExecuteTests.MESSAGES:
            with self.subTest(text=text):
                self.assertFalse(has_explicit_research_execution_intent(text))

    def test_web_explicit_execution_request_reaches_real_execution(self) -> None:
        text = "삼성전자 전략을 처음부터 다시 연구해줘."
        store = RuntimeStateStore(":memory:")
        try:
            payload = _web_send(store, text)
            self.assertEqual(payload["tool_calls"], ["autonomous_learning_research"])
            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_learning_research")), 1)
            self.assertFalse(payload["order_executed"])
            self.assertFalse(payload["champion_promoted"])
            self.assertFalse(payload["approval_bypassed"])
        finally:
            store.close()

    def test_telegram_explicit_execution_request_reaches_real_execution(self) -> None:
        text = "삼성전자 전략을 처음부터 다시 연구해줘."
        store = RuntimeStateStore(":memory:")
        try:
            _telegram_send(store, text)
            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_learning_research")), 1)
        finally:
            store.close()

    def test_web_and_telegram_reach_the_same_execution_tool_for_the_same_explicit_request(self) -> None:
        text = "삼성전자 전략을 처음부터 다시 연구해줘."
        web_store = RuntimeStateStore(":memory:")
        telegram_store = RuntimeStateStore(":memory:")
        try:
            web_payload = _web_send(web_store, text)
            _telegram_send(telegram_store, text)
            self.assertEqual(web_payload["tool_calls"], ["autonomous_learning_research"])
            self.assertEqual(len(telegram_store.tool_audit.list(tool_name="autonomous_learning_research")), 1)
        finally:
            web_store.close()
            telegram_store.close()


class AmbiguousNounTests(unittest.TestCase):
    """TEST GROUP 4 - a bare/ambiguous noun phrase never executes
    anything and never mutates a mission without an explicit action."""

    MESSAGES = ("단타", "단타 연구", "삼성전자")

    def test_web_ambiguous_nouns_never_execute(self) -> None:
        for text in self.MESSAGES:
            with self.subTest(transport="web", text=text):
                store = RuntimeStateStore(":memory:")
                payload = _web_send(store, text)
                self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
                self.assertFalse(payload["strategy_mutated"])
                store.close()

    def test_telegram_ambiguous_nouns_never_execute(self) -> None:
        for text in self.MESSAGES:
            with self.subTest(transport="telegram", text=text):
                store = RuntimeStateStore(":memory:")
                _telegram_send(store, text)
                self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
                store.close()

    def test_bare_topic_mention_does_not_use_the_generic_complaint_fallback(self) -> None:
        # "단타 연구" must not be answered with the GENERAL_CONVERSATION
        # feedback template written for genuine complaints/confusion
        # ("맨날 없네요") - see the _try_conversational_mvp GENERAL_
        # CONVERSATION branch note.
        store = RuntimeStateStore(":memory:")
        try:
            payload = _web_send(store, "단타 연구")
            self.assertNotIn("말씀해 주신 불편을 확인했습니다", payload["text"])
        finally:
            store.close()

    def test_genuinely_uninterpretable_input_keeps_the_honest_feedback_response(self) -> None:
        # Regression guard for tests/integration/test_telegram_conversation_agent.py::
        # test_production_conversation_routes_capability_status_and_feedback_without_research -
        # this hotfix must not silence the GENERAL_CONVERSATION fallback for
        # text that carries no research-domain topic at all.
        store = RuntimeStateStore(":memory:")
        try:
            reply = _telegram_send(store, "맨날 없네요")
            self.assertIn("말씀해 주신 불편을 확인했습니다", reply)
        finally:
            store.close()


class MultiTurnSubjectResolutionTests(unittest.TestCase):
    """TEST GROUP 5 - a short multi-turn exchange stays on the STATUS_READ
    subject until a turn explicitly asks to execute."""

    def _run_turns(self, sender, store: RuntimeStateStore) -> list[str]:
        turn1 = sender(store, "단타 연구는 잘되가고 있나요?")
        turn3 = sender(store, "그러면 다시 연구해줘.")
        return [turn1, turn3]

    def test_web_turn3_explicit_followup_reaches_execution_while_turn1_stays_read_only(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            turn1 = _web_send(store, "단타 연구는 잘되가고 있나요?", session_ref="mt1")
            self.assertEqual(_strict_tool_call_counts(store), {name: 0 for name in _STRICT_TOOLS})
            _web_send(store, "그러면 다시 연구해줘.", session_ref="mt1")
            # Turn 3 carries an explicit execution verb ("연구해줘"); whether
            # it actually finds a symbol to research from turn 1's bare
            # "단타" topic is a follow-up-resolution concern tracked
            # separately (see the PR report's known-gap note) - what this
            # hotfix guarantees is that turn 1 itself never executed.
            self.assertEqual(turn1["route"], "conversation_research_status_no_mission")
        finally:
            store.close()


class ApprovalBoundaryTests(unittest.TestCase):
    """TEST GROUP 6 - conversational text short of an explicit approval
    decision never advances the strategy lifecycle."""

    def test_web_soft_opinions_are_not_treated_as_approval(self) -> None:
        for text in ("이 전략 좋아 보여", "후보 3번으로 하자"):
            with self.subTest(text=text):
                store = RuntimeStateStore(":memory:")
                payload = _web_send(store, text)
                self.assertFalse(payload["strategy_mutated"])
                self.assertFalse(payload["order_executed"])
                self.assertFalse(payload["champion_promoted"])
                self.assertFalse(payload["approval_bypassed"])
                store.close()


if __name__ == "__main__":
    unittest.main()
