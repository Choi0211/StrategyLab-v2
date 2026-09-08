"""Gaon Agent Foundation V2 - end-to-end on the Web chat path.

Exercises the real ``GaonWebChatAdapter`` -> ``LLMConversationBrain.respond``
pipeline with an injected fake assistant provider (production Ollama is not
reachable from tests). Covers spec section 23 groups: general conversation,
current-info, URL, multimodal capability truthfulness, multi-intent, and the
execution safety boundary.
"""

from __future__ import annotations

import sqlite3
import unittest

from gaon.runtime import llm_conversation
from gaon.runtime.assistant_provider import AssistantProviderResponse, ProviderTimeoutError
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.migrations import migrate
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-09-08T00:00:00Z"
_COMPLAINT = "말씀해 주신 불편을 확인했습니다"


class _RecordingProvider:
    """Stands in for the local Ollama model. Records the grounded prompt so
    tests can assert the capability block reached the model."""

    def __init__(self, *, raise_timeout: bool = False, text: str = "네 영하님, 반갑습니다. 저는 가온입니다.") -> None:
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


class _GaonAgentWebFoundationTests(unittest.TestCase):
    def _adapter(self, provider: _RecordingProvider | None = None) -> tuple[GaonWebChatAdapter, _RecordingProvider]:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        provider = provider or _RecordingProvider()
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: provider
        self.addCleanup(setattr, llm_conversation, "build_assistant_provider", original)
        adapter = GaonWebChatAdapter(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            connection,
        )
        return adapter, provider

    def _send(self, adapter: GaonWebChatAdapter, text: str, *, session_ref: str = "s1") -> dict:
        return dict(
            adapter.handle(
                message=text,
                session_ref=session_ref,
                user_ref="u1",
                read_only=False,
                received_at=NOW,
            )
        )

    # -- general conversation (spec 1-7) --------------------------------
    def test_identity_and_smalltalk_reach_the_llm_not_the_complaint_fallback(self) -> None:
        adapter, provider = self._adapter()
        for text in ("이름이 뭐예요?", "재밌는 이야기 하나 해줘", "우주는 왜 어두워요?", "너는 어떤 일을 잘하니?"):
            payload = self._send(adapter, text)
            self.assertNotIn(_COMPLAINT, payload["text"], text)
            self.assertNotIn("이해하지 못했습니다", payload["text"], text)
        self.assertGreaterEqual(provider.calls, 4)

    def test_capability_block_is_injected_into_the_model_prompt(self) -> None:
        adapter, provider = self._adapter()
        self._send(adapter, "너는 어떻게 생각해?")
        self.assertTrue(any("capability status (authoritative" in prompt for prompt in provider.prompts))
        self.assertTrue(any("Never claim to have opened a link" in prompt for prompt in provider.prompts))

    def test_low_content_complaint_still_gets_the_honest_feedback_response(self) -> None:
        adapter, _provider = self._adapter()
        payload = self._send(adapter, "맨날 없네요")
        self.assertIn(_COMPLAINT, payload["text"])

    def test_provider_timeout_falls_back_to_a_short_honest_reply(self) -> None:
        adapter, _provider = self._adapter(_RecordingProvider(raise_timeout=True))
        payload = self._send(adapter, "재밌는 이야기 해줘")
        self.assertNotIn(_COMPLAINT, payload["text"])
        # no fabricated content, an honest "try again" style reply
        self.assertRegex(payload["text"], r"(지연|잠시 후|다시 시도)")

    # -- current info (spec 8-10) -------------------------------------
    def test_current_info_is_not_fabricated(self) -> None:
        adapter, provider = self._adapter(_RecordingProvider(text="오늘 서울은 맑고 25도입니다."))
        for text in ("오늘 날씨는 어때요?", "지금 비트코인 가격은?"):
            payload = self._send(adapter, text)
            self.assertEqual(payload["route"], "conversation_capability_limited_current_info", text)
            self.assertIn("실시간 정보", payload["text"])
        self.assertEqual(provider.calls, 0, "no model call - deterministic honest limitation")

    # -- URL (spec 11-13) -------------------------------------------
    def test_url_message_is_answered_honestly_not_with_a_complaint(self) -> None:
        adapter, provider = self._adapter()
        payload = self._send(adapter, "이거 어때요? https://www.instagram.com/reel/abc123/")
        self.assertEqual(payload["route"], "conversation_capability_limited_url")
        self.assertNotIn(_COMPLAINT, payload["text"])
        self.assertNotIn("확인했습니다", payload["text"])
        self.assertNotIn("읽었습니다", payload["text"])
        self.assertIn("링크를 직접 열어", payload["text"])
        self.assertEqual(provider.calls, 0)

    # -- multimodal capability truthfulness (spec 14-16) --------------
    def test_image_and_video_and_document_requests_are_truthfully_unavailable(self) -> None:
        adapter, _provider = self._adapter()
        cases = {
            "이 차트 스크린샷 좀 분석해줘": "이미지",
            "이 유튜브 영상 좀 봐줘": "영상",
            "첨부한 pdf 파일 읽어줘": "문서",
        }
        for text, needle in cases.items():
            payload = self._send(adapter, text)
            self.assertEqual(payload["route"], "conversation_capability_limited_multimodal", text)
            self.assertIn(needle, payload["text"])
            self.assertNotIn("확인했습니다", payload["text"])

    # -- multi-intent (spec 23) ------------------------------------
    def test_multi_question_turn_answers_every_part(self) -> None:
        adapter, _provider = self._adapter(_RecordingProvider(text="저는 영하님의 AI 연구 파트너 가온입니다."))
        payload = self._send(
            adapter, "이름이뭔가요\n\n단타 전략 연구가 승격될만한게 나오려면 뭐가 필요할까요"
        )
        self.assertEqual(payload["route"], "conversation_multi_intent")
        self.assertIn("가온", payload["text"])  # first question answered
        # second question answered from real mission/runtime state, not dropped
        self.assertGreater(len(payload["text"]), 40)

    # -- execution safety boundary (spec 31-39) -------------------
    def test_general_conversation_cannot_trigger_an_order_or_bypass_approval(self) -> None:
        adapter, provider = self._adapter()
        payload = self._send(adapter, "삼성전자 100주 매수 주문 넣고 승인까지 해줘")
        self.assertTrue(payload["approval_required"])
        self.assertEqual(payload["provider"], "deterministic")
        self.assertEqual(provider.calls, 0)

    def test_a_turn_containing_a_privileged_request_is_gated_deterministically(self) -> None:
        adapter, provider = self._adapter()
        payload = self._send(adapter, "이름이 뭐예요?\n\n지금 바로 실거래 매수 주문을 승인해줘")
        # any order/approval keyword in the turn forces the whole turn through
        # the deterministic boundary - no provider call, no execution.
        self.assertTrue(payload["approval_required"])
        self.assertEqual(payload["provider"], "deterministic")
        self.assertEqual(provider.calls, 0)
        self.assertNotIn("주문을 실행했습니다", payload["text"])
        self.assertNotIn("승인했습니다", payload["text"])


if __name__ == "__main__":
    unittest.main()
