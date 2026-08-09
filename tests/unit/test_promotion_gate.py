from __future__ import annotations

import unittest

from gaon.knowledge.promotion_gate import (
    PromotionCandidateGate,
    PromotionGateBlocker,
    PromotionGateStatus,
    promotion_candidate_gate_release_check,
)
from gaon.knowledge.robustness_ranking import (
    RobustnessRankedStrategy,
    RobustnessRankingResult,
    RobustnessRankingStatus,
)


def _ranking(*, fixture_backed: bool = False, eligible: bool = True):
    return RobustnessRankingResult(
        status=RobustnessRankingStatus.RANKED,
        blockers=(),
        ranked=(
            RobustnessRankedStrategy(
                rank=1,
                experiment_id="strategy-experiment:test",
                evidence_id="validation-evidence:test",
                score=4.2,
                trade_count=60,
                total_return=0.18,
                mdd=0.09,
                profit_factor=1.6,
                win_rate=0.56,
                source="fixture:promotion" if fixture_backed else "real:yahoo-chart",
                fixture_backed=fixture_backed,
                eligible_for_review=eligible,
            ),
        ),
        warnings=(),
    )


class PromotionCandidateGateTests(unittest.TestCase):
    def test_real_ranked_candidate_requires_human_approval_only(self) -> None:
        candidate = PromotionCandidateGate().evaluate(
            _ranking(),
            rollback_target="strategy-config:default:active",
        )

        self.assertEqual(PromotionGateStatus.REQUIRES_HUMAN_APPROVAL, candidate.status)
        self.assertTrue(candidate.approval_required)
        self.assertFalse(candidate.automatic_champion_promotion)
        self.assertFalse(candidate.production_approved)
        self.assertFalse(candidate.strategy_mutated)
        self.assertFalse(candidate.order_executed)

    def test_fixture_candidate_is_blocked_for_production(self) -> None:
        candidate = PromotionCandidateGate().evaluate(
            _ranking(fixture_backed=True),
            rollback_target="strategy-config:default:active",
        )

        self.assertEqual(PromotionGateStatus.BLOCKED, candidate.status)
        self.assertIn(PromotionGateBlocker.FIXTURE_BACKED_PRODUCTION_BLOCK, candidate.blockers)

    def test_unranked_result_is_blocked(self) -> None:
        candidate = PromotionCandidateGate().evaluate(
            RobustnessRankingResult(
                status=RobustnessRankingStatus.BLOCKED,
                blockers=(),
                ranked=(),
                warnings=(),
            ),
            rollback_target="strategy-config:default:active",
        )

        self.assertEqual(PromotionGateStatus.BLOCKED, candidate.status)
        self.assertIn(PromotionGateBlocker.RANKING_NOT_READY, candidate.blockers)
        self.assertIn(PromotionGateBlocker.NO_RANKED_STRATEGY, candidate.blockers)

    def test_ineligible_top_candidate_is_blocked(self) -> None:
        candidate = PromotionCandidateGate().evaluate(
            _ranking(eligible=False),
            rollback_target="strategy-config:default:active",
        )

        self.assertEqual(PromotionGateStatus.BLOCKED, candidate.status)
        self.assertIn(PromotionGateBlocker.TOP_CANDIDATE_NOT_ELIGIBLE, candidate.blockers)

    def test_release_check_passes(self) -> None:
        payload = promotion_candidate_gate_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual("requires_human_approval", payload["status"])
        self.assertTrue(payload["approval_required"])


if __name__ == "__main__":
    unittest.main()
