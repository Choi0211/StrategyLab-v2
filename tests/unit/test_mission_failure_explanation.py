"""ULTRAREVIEW H4 - truthful tool-failure explanation unit tests.

``LLMConversationBrain._format_multi_tool_response_for_session`` used to
unconditionally claim "adaptive budget exhaustion" whenever every tool call
in a turn failed, regardless of the ACTUAL recorded cause. These tests
exercise ``_classify_multi_tool_failure`` (the pure classifier the fix
introduced) directly against the structured failure shapes the real
``SafeToolExecutor``/tool handlers actually produce, and prove each cause
gets its own distinct, truthful explanation - never a fabricated one -
while a policy/safety denial is reported as a policy restriction, not a
budget or data problem, and never leaks raw exception internals.
"""

from __future__ import annotations

import unittest

from gaon.runtime.assistant_provider import AssistantToolResult
from gaon.runtime.llm_conversation import (
    _POLICY_DENIAL_TEXT,
    _TIMEOUT_TEXT,
    _UNCLEAR_TOOL_FAILURE_TEXT,
    _classify_multi_tool_failure,
)


def _failed_result(*, error_type: str, message: str, tool_name: str = "multi_symbol_research") -> AssistantToolResult:
    return AssistantToolResult(
        call_id=f"call:{tool_name}",
        name=tool_name,
        result={"status": "denied", "output": {"error_type": error_type, "message": message}, "warnings": ["tool denied"]},
    )


class ClassifyMultiToolFailureTests(unittest.TestCase):
    def test_policy_denial_reports_a_policy_restriction_not_a_data_problem(self) -> None:
        result = _failed_result(error_type="ToolSecurityError", message="unexpected tool arguments: broker_order")
        self.assertEqual(_classify_multi_tool_failure((result,)), _POLICY_DENIAL_TEXT)

    def test_timeout_reports_a_timeout_explanation(self) -> None:
        result = _failed_result(error_type="TimeoutError", message="provider request timed out after 20s")
        self.assertEqual(_classify_multi_tool_failure((result,)), _TIMEOUT_TEXT)

    def test_provider_data_failure_reports_market_data_explanation(self) -> None:
        result = _failed_result(error_type="RealMarketDataUnavailable", message="real_data_unavailable: no bars returned")
        explanation = _classify_multi_tool_failure((result,))
        self.assertNotEqual(explanation, _UNCLEAR_TOOL_FAILURE_TEXT)
        self.assertNotEqual(explanation, _POLICY_DENIAL_TEXT)
        self.assertIn("시장 데이터", explanation)

    def test_data_quality_failure_reports_quality_explanation(self) -> None:
        result = _failed_result(error_type="RealMarketDataUnavailable", message="real_data_unavailable: blocking_quality invalid_ohlc")
        explanation = _classify_multi_tool_failure((result,))
        self.assertIn("품질", explanation)

    def test_unknown_cause_falls_back_to_truthful_unclear_message(self) -> None:
        result = _failed_result(error_type="KeyError", message="'unexpected_field'")
        self.assertEqual(_classify_multi_tool_failure((result,)), _UNCLEAR_TOOL_FAILURE_TEXT)
        self.assertIn("확정할 수 없습니다", _UNCLEAR_TOOL_FAILURE_TEXT)

    def test_mixed_causes_across_results_fall_back_to_unclear_rather_than_pick_one(self) -> None:
        results = (
            _failed_result(error_type="ToolSecurityError", message="unexpected tool arguments"),
            _failed_result(error_type="RealMarketDataUnavailable", message="real_data_unavailable: no bars returned"),
        )
        self.assertEqual(_classify_multi_tool_failure(results), _UNCLEAR_TOOL_FAILURE_TEXT)

    def test_never_leaks_raw_exception_message_or_internal_paths(self) -> None:
        secret_path = "C:\\Users\\super\\secrets\\api_key.txt"
        result = _failed_result(error_type="RuntimeError", message=f"failed to read token from {secret_path}: token=sk-abc123")
        explanation = _classify_multi_tool_failure((result,))
        self.assertNotIn(secret_path, explanation)
        self.assertNotIn("sk-abc123", explanation)
        self.assertNotIn("token=", explanation)

    def test_no_results_falls_back_to_unclear(self) -> None:
        self.assertEqual(_classify_multi_tool_failure(()), _UNCLEAR_TOOL_FAILURE_TEXT)


if __name__ == "__main__":
    unittest.main()
