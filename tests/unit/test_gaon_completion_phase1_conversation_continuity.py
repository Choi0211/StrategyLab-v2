from __future__ import annotations
import unittest
from gaon.runtime.conversational_mvp import ConversationalMVPIntent, classify_conversational_route
from gaon.runtime.llm_conversation import _autonomous_learning_request_mode, _autonomous_request_mode

class GaonCompletionPhase1ConversationContinuityTests(unittest.TestCase):
    def test_natural_result_recall(self):
        for text in ("결과가 뭔가요?", "그래서 결과가 뭐예요?", "방금 연구 결과 알려줘", "최종 결론이 뭐예요?", "그래서 어떻게 됐나요?"):
            with self.subTest(text=text):
                self.assertEqual(ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT, classify_conversational_route(text).intent)

    def test_natural_continuation(self):
        for text in ("다음 연구 진행해주세요", "이어서 연구해주세요", "증거가 충분할 때까지 계속 연구해주세요", "근거가 충분해질 때까지 계속해주세요", "결론을 내릴 수 있을 때까지 연구를 이어가주세요"):
            with self.subTest(text=text):
                self.assertEqual("continue", _autonomous_request_mode(text))
                self.assertEqual("continue", _autonomous_learning_request_mode(text))

    def test_result_recall_does_not_start_research(self):
        text = "그래서 연구 결과가 뭔가요?"
        self.assertIsNone(_autonomous_request_mode(text))
        self.assertIsNone(_autonomous_learning_request_mode(text))

if __name__ == "__main__":
    unittest.main()
