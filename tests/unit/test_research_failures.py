import unittest

from gaon.runtime.assistant_provider import ProviderTimeoutError
from gaon.runtime.research_failures import classify_exception, classify_tool_failure


class ResearchFailureClassificationTests(unittest.TestCase):
    def test_market_data_unavailable_is_not_llm_timeout(self) -> None:
        failure = classify_tool_failure("RealMarketDataUnavailable", "real_data_unavailable: provider returned no usable bars")

        self.assertEqual(failure.stage, "market_data")
        self.assertIn("실제 시장 데이터를 가져오지 못해", failure.user_message)
        self.assertNotIn("로컬 LLM", failure.user_message)

    def test_quality_and_backtest_failures_have_specific_messages(self) -> None:
        quality = classify_tool_failure("RealMarketDataUnavailable", "real_data_unavailable: blocking_quality_findings=invalid_ohlc")
        backtest = classify_tool_failure("RuntimeError", "backtest execution failed")

        self.assertEqual(quality.stage, "quality")
        self.assertIn("데이터 품질", quality.user_message)
        self.assertEqual(backtest.stage, "backtest")
        self.assertIn("백테스트 실행 중 오류", backtest.user_message)

    def test_provider_timeout_remains_llm_delay(self) -> None:
        failure = classify_exception(ProviderTimeoutError("slow"))

        self.assertEqual(failure.stage, "llm")
        self.assertIn("로컬 LLM 응답이 지연", failure.user_message)

    def test_unexpected_exception_is_internal_without_traceback(self) -> None:
        failure = classify_exception(RuntimeError("secret traceback details"))

        self.assertEqual(failure.stage, "internal")
        self.assertIn("내부 오류", failure.user_message)
        self.assertNotIn("secret traceback details", failure.user_message)


if __name__ == "__main__":
    unittest.main()
