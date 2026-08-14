from __future__ import annotations

import unittest

from gaon.knowledge.autonomous_quant_partner import (
    _release_baseline_with_real_execution_inputs,
    _release_multi_source_result,
)
from gaon.knowledge.telegram_autonomous_learning import (
    production_autonomous_learning_payload_from_baseline,
)
from gaon.runtime.research_grounding import format_grounded_tool_response


class FinalProductionResearchWiringTests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        baseline = _release_baseline_with_real_execution_inputs()
        multi_source = _release_multi_source_result(baseline)
        external = {
            "schema_version": 2,
            "state": "academic_content_exhausted",
            "question_id": "research-question:final-wiring",
            "discovery_run": {"results": []},
            "normalized_records": [],
            "candidates": [],
            "blockers": ["academic_content_exhausted"],
            "network_executed": True,
            "multi_source_research": multi_source,
        }
        return dict(
            production_autonomous_learning_payload_from_baseline(
                "Samsung final production research wiring",
                symbol="005930",
                mode="research",
                baseline=baseline,
                external_research=external,
            )
        )

    def test_generic_detail_uses_quant_partner_not_legacy_promotion_renderer(self) -> None:
        payload = self._payload()
        rendered = format_grounded_tool_response(
            "autonomous_learning_research",
            payload,
            "상세 검증 결과 보여줘",
        )
        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("[Autonomous Quant Partner]", rendered)
        self.assertIn("[실제 외부 Provider 상태]", rendered)
        self.assertIn("[Adaptive Validation Feedback]", rendered)
        self.assertNotIn("[승격 후보]", rendered)

    def test_explicit_promotion_candidate_request_keeps_promotion_renderer(self) -> None:
        payload = self._payload()
        rendered = format_grounded_tool_response(
            "autonomous_learning_research",
            payload,
            "승격 후보 상세 보여줘",
        )
        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("[승격 후보]", rendered)

    def test_authoritative_summary_preserves_adaptive_execution(self) -> None:
        payload = self._payload()
        learning = payload["autonomous_learning_v2"]
        summary = payload["production_validation_execution_summary"]
        self.assertIn("adaptive_validation_feedback", payload)
        self.assertIn("adaptive_validation_feedback", learning)
        self.assertIn("adaptive_actual_retests", summary)
        self.assertIn("adaptive_feedback_executed", summary)
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])


if __name__ == "__main__":
    unittest.main()
