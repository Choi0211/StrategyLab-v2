from __future__ import annotations

import unittest

from gaon.knowledge.human_gated_promotion import (
    HumanGatedPromotionBlocker,
    HumanGatedPromotionService,
    HumanGatedPromotionStatus,
    approval_token_for_candidate,
    autonomous_learning_production_gate_release_check,
    human_gated_promotion_release_check,
)
from gaon.knowledge.promotion_gate import PromotionCandidateGate
from gaon.knowledge.robustness_ranking import (
    RobustnessRankedStrategy,
    RobustnessRankingResult,
    RobustnessRankingStatus,
)


def _candidate():
    ranking = RobustnessRankingResult(
        status=RobustnessRankingStatus.RANKED,
        blockers=(),
        ranked=(
            RobustnessRankedStrategy(
                rank=1,
                experiment_id="strategy-experiment:test-human",
                evidence_id="validation-evidence:test-human",
                score=4.2,
                trade_count=60,
                total_return=0.18,
                mdd=0.09,
                profit_factor=1.6,
                win_rate=0.56,
                source="real:yahoo-chart",
                fixture_backed=False,
            ),
        ),
        warnings=(),
    )
    return PromotionCandidateGate().evaluate(
        ranking,
        rollback_target="strategy-config:default:active",
    )


class HumanGatedPromotionTests(unittest.TestCase):
    def test_missing_approval_waits_without_mutation(self) -> None:
        candidate = _candidate()
        result = HumanGatedPromotionService().evaluate(
            candidate,
            approval_token=None,
            signing_secret="secret",
            approved_by="actor:redacted",
            approved_at="2026-08-08T00:00:00+00:00",
            reason="manual review",
        )

        self.assertEqual(HumanGatedPromotionStatus.AWAITING_HUMAN_APPROVAL, result.status)
        self.assertIn(HumanGatedPromotionBlocker.MISSING_APPROVAL, result.blockers)
        self.assertFalse(result.strategy_mutated)
        self.assertFalse(result.order_executed)

    def test_invalid_token_blocks_fail_closed(self) -> None:
        candidate = _candidate()
        result = HumanGatedPromotionService().evaluate(
            candidate,
            approval_token="invalid",
            signing_secret="secret",
            approved_by="actor:redacted",
            approved_at="2026-08-08T00:00:00+00:00",
            reason="manual review",
        )

        self.assertEqual(HumanGatedPromotionStatus.BLOCKED, result.status)
        self.assertIn(HumanGatedPromotionBlocker.INVALID_APPROVAL_TOKEN, result.blockers)

    def test_valid_token_approves_manual_application_only(self) -> None:
        candidate = _candidate()
        token = approval_token_for_candidate(candidate.candidate_id, "secret")
        result = HumanGatedPromotionService().evaluate(
            candidate,
            approval_token=token,
            signing_secret="secret",
            approved_by="actor:redacted",
            approved_at="2026-08-08T00:00:00+00:00",
            reason="manual review",
        )

        self.assertEqual(
            HumanGatedPromotionStatus.APPROVED_FOR_MANUAL_APPLICATION,
            result.status,
        )
        self.assertTrue(result.production_approved)
        self.assertTrue(result.manual_application_required)
        self.assertFalse(result.automatic_champion_promotion)
        self.assertFalse(result.strategy_mutated)
        self.assertFalse(result.order_executed)
        self.assertNotIn(token, str(result.to_json()))

    def test_release_checks_pass(self) -> None:
        human = human_gated_promotion_release_check()
        aggregate = autonomous_learning_production_gate_release_check()

        self.assertEqual("pass", human["safety"])
        self.assertEqual("production_gate_ready", aggregate["status"])


if __name__ == "__main__":
    unittest.main()
