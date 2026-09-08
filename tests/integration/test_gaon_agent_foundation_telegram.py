"""Gaon Agent Foundation V2 - end-to-end on the Telegram chat path.

Same behaviour contract as the Web test, through ``TelegramConversationAgent``
(which accepts an injected assistant provider directly).
"""

from __future__ import annotations

import sqlite3
import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse, ProviderTimeoutError
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.conversation import ConversationInput
from gaon.runtime.migrations import migrate
from gaon.runtime.telegram_agent import TelegramConversationAgent

NOW = "2026-09-08T00:00:00Z"
_COMPLAINT = "말씀해 주신 불편을 확인했습니다"


class _RecordingProvider:
    def __init__(self, *, raise_timeout: bool = False, text: str = "네 영하님, 저는 가온입니다.") -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self._raise_timeout = raise_timeout
        self._text = text

    def respond(self, request):  # noqa: ANN001 - test double
        self.calls += 1
        self.prompts.append(request.prompt or request.text)
        if self._raise_timeout:
            raise ProviderTimeoutError("local model timed out")
        return AssistantProviderResponse(text=self._text, provider_name="openai-compatible")


class GaonAgentTelegramFoundationTests(unittest.TestCase):
    def _agent(self, provider: _RecordingProvider | None = None) -> tuple[TelegramConversationAgent, _RecordingProvider]:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        provider = provider or _RecordingProvider()
        agent = TelegramConversationAgent(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            connection,
            assistant_provider=provider,
        )
        return agent, provider

    def _send(self, agent: TelegramConversationAgent, text: str, *, mid: int = 1) -> str:
        response = agent.handle(
            ConversationInput(
                source="telegram",
                user_id="8767020479",
                conversation_id="100",
                message_id=str(mid),
                text=text,
                received_at=NOW,
            )
        )
        return response.text, response.route, response.approval_required

    def test_general_conversation_reaches_the_model(self) -> None:
        agent, provider = self._agent()
        text, _route, _approval = self._send(agent, "이름이 뭐예요?")
        self.assertNotIn(_COMPLAINT, text)
        self.assertNotIn("이해하지 못했습니다", text)
        self.assertEqual(provider.calls, 1)

    def test_url_is_not_a_complaint_and_no_content_is_claimed(self) -> None:
        agent, provider = self._agent()
        text, route, _approval = self._send(agent, "이건 어때요? https://instagram.com/p/xyz")
        self.assertEqual(route, "conversation_capability_limited_url")
        self.assertNotIn(_COMPLAINT, text)
        self.assertNotIn("게시물을 확인했습니다", text)
        self.assertEqual(provider.calls, 0)

    def test_current_info_is_not_fabricated(self) -> None:
        agent, provider = self._agent(_RecordingProvider(text="오늘은 맑고 25도입니다"))
        text, route, _approval = self._send(agent, "오늘의 날씨는 어떤가요")
        self.assertEqual(route, "conversation_capability_limited_current_info")
        self.assertIn("실시간 정보", text)
        self.assertEqual(provider.calls, 0)

    def test_video_request_is_truthfully_unavailable(self) -> None:
        agent, _provider = self._agent()
        text, route, _approval = self._send(agent, "가온아 이 영상 한번 봐봐")
        self.assertEqual(route, "conversation_capability_limited_multimodal")
        self.assertIn("영상", text)
        self.assertNotIn("확인했습니다", text)

    def test_multi_intent_answers_both_questions(self) -> None:
        agent, _provider = self._agent(_RecordingProvider(text="저는 가온입니다."))
        text, route, _approval = self._send(
            agent, "이름이뭔가요\n\n단타 전략 연구가 승격될만한게 나오려면 뭐가 필요할까요"
        )
        self.assertEqual(route, "conversation_multi_intent")
        self.assertIn("가온", text)
        self.assertGreater(len(text), 40)

    def test_order_request_bypasses_the_provider_and_requires_approval(self) -> None:
        agent, provider = self._agent()
        text, _route, approval = self._send(agent, "삼성전자 매수 주문 승인해줘")
        self.assertTrue(approval)
        self.assertEqual(provider.calls, 0)

    def test_capability_question_lists_real_capabilities_and_honest_limits(self) -> None:
        agent, _provider = self._agent()
        text, route, _approval = self._send(agent, "무엇을 할 수 있나요?")
        self.assertEqual(route, "conversation_mvp_help")
        self.assertIn("실제로 할 수 있는 일", text)
        self.assertIn("아직 못 하는 일", text)
        self.assertNotIn("삼성전자 분석해줘", text)


if __name__ == "__main__":
    unittest.main()
