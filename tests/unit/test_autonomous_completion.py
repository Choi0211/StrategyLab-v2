import unittest

from gaon.research.autonomous_completion import (
    AdaptiveResearchValidator,
    AdequacyStatus,
    ValidationNeedKind,
    ValidationStopReason,
    gaon_adaptive_validation_release_check,
)


class AdaptiveResearchValidationTests(unittest.TestCase):
    def test_insufficient_sample_generates_validation_needs(self) -> None:
        assessment = AdaptiveResearchValidator().assess(
            {
                "metrics": {"trade_count": 1, "wins": 1, "losses": 0, "mdd": 0.04},
                "observation_days": 120,
                "market_regime_count": 1,
                "quality": {"status": "pass"},
                "symbol_coverage": {"symbol_count": 1, "eligible_symbol_count": 1},
                "evidence_refs": ("backtest:1",),
            }
        )

        self.assertEqual(assessment.status, AdequacyStatus.INSUFFICIENT)
        self.assertEqual(assessment.plan.stop_reason, ValidationStopReason.INSUFFICIENT_SAMPLE)
        self.assertFalse(assessment.plan.can_change_strategy)
        self.assertIn(ValidationNeedKind.EXTEND_PERIOD, {need.kind for need in assessment.plan.needs})
        self.assertIn("backtest:1", assessment.evidence_refs)

    def test_blocking_quality_is_invalid_fail_closed(self) -> None:
        assessment = AdaptiveResearchValidator().assess(
            {
                "metrics": {"trade_count": 80, "wins": 40, "losses": 40, "mdd": 0.1},
                "observation_days": 800,
                "market_regime_count": 3,
                "quality": {"status": "fail", "missing_bar_count": 1},
            }
        )

        self.assertEqual(assessment.status, AdequacyStatus.INVALID)
        self.assertEqual(assessment.plan.stop_reason, ValidationStopReason.DATA_QUALITY_BLOCKING)

    def test_sufficient_evidence_has_no_plan_needs(self) -> None:
        assessment = AdaptiveResearchValidator().assess(
            {
                "metrics": {"trade_count": 45, "wins": 25, "losses": 20, "mdd": 0.12},
                "observation_days": 900,
                "market_regime_count": 3,
                "quality": {"status": "pass"},
                "symbol_coverage": {"symbol_count": 5, "eligible_symbol_count": 5},
            }
        )

        self.assertEqual(assessment.status, AdequacyStatus.SUFFICIENT)
        self.assertEqual(assessment.plan.needs, ())

    def test_release_check_passes(self) -> None:
        result = gaon_adaptive_validation_release_check()

        self.assertEqual(result["safety"], "pass")


if __name__ == "__main__":
    unittest.main()
