import unittest

from strategylab.research.ai_review import (
    AIReviewInput,
    AIReviewResult,
    AIReviewStatus,
    build_review_prompt,
    fallback_review,
    validate_review_result,
)


class AIResearchTest(unittest.TestCase):
    def test_prompt_assembly_is_deterministic(self) -> None:
        review_input = AIReviewInput(
            strategy_name="demo",
            metrics={"sharpe": 1.2, "mdd": -0.1},
            risk_notes=("drawdown acceptable",),
            assumptions=("synthetic fixture",),
        )
        self.assertEqual(build_review_prompt(review_input), build_review_prompt(review_input))
        self.assertIn("- mdd: -0.1", build_review_prompt(review_input))

    def test_review_result_validation(self) -> None:
        result = AIReviewResult(AIReviewStatus.PASS, "ok", ("metric evidence",), ("fixture only",))
        self.assertEqual(validate_review_result(result), result)

    def test_review_result_requires_summary_and_evidence(self) -> None:
        with self.assertRaises(ValueError):
            validate_review_result(AIReviewResult(AIReviewStatus.WARN, "", ("evidence",), ()))
        with self.assertRaises(ValueError):
            validate_review_result(AIReviewResult(AIReviewStatus.WARN, "summary", (), ()))

    def test_fallback_review_is_explicit(self) -> None:
        result = fallback_review("no api configured")
        self.assertEqual(result.status, AIReviewStatus.WARN)
        self.assertIn("manual review", result.summary)


if __name__ == "__main__":
    unittest.main()

