from __future__ import annotations

import unittest
from dataclasses import replace

from gaon.knowledge.research_mission import (
    MissionStatus,
    add_candidate,
    extract_or_update_mission,
    get_active_candidate,
    next_candidate_sequence,
    record_blocked,
)
from gaon.knowledge.strategy_candidate import StrategyCandidateStatus, new_candidate
from gaon.runtime.autonomous_research_runtime import attempt_bounded_stagnation_recovery

_NOW = "2026-08-22T00:00:05Z"


def _market_wide_mission():
    return extract_or_update_mission(
        "국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요",
        existing=None,
        now=_NOW,
    )


def _stagnant_candidate(mission, *, reason: str):
    candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=_NOW)
    return replace(candidate, status=StrategyCandidateStatus.STAGNANT, rejected_reason=reason, cycles_without_progress=5)


class AttemptBoundedStagnationRecoveryTests(unittest.TestCase):
    def test_non_blocked_mission_is_untouched(self) -> None:
        mission = _market_wide_mission()
        recovered, did_recover = attempt_bounded_stagnation_recovery(mission, now=_NOW)
        self.assertIs(recovered, mission)
        self.assertFalse(did_recover)

    def test_blocked_for_unrelated_reason_is_untouched(self) -> None:
        mission = record_blocked(_market_wide_mission(), reason="provider_unavailable: no data source responded", now=_NOW)
        recovered, did_recover = attempt_bounded_stagnation_recovery(mission, now=_NOW)
        self.assertIs(recovered, mission)
        self.assertFalse(did_recover)
        self.assertEqual(recovered.status, MissionStatus.BLOCKED)
        self.assertEqual(recovered.blocked_reason, "provider_unavailable: no data source responded")

    def test_recovers_a_stalled_not_exhausted_stagnant_candidate(self) -> None:
        mission = _market_wide_mission()
        stalled = _stagnant_candidate(mission, reason="validation_cycle_exhausted_without_progress")
        mission = add_candidate(mission, stalled, now=_NOW)
        mission = record_blocked(
            mission,
            reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted",
            now=_NOW,
        )

        recovered, did_recover = attempt_bounded_stagnation_recovery(mission, now=_NOW)

        self.assertTrue(did_recover)
        self.assertEqual(recovered.status, MissionStatus.ACTIVE)
        self.assertIsNone(recovered.blocked_reason)
        active = get_active_candidate(recovered)
        self.assertIsNotNone(active)
        self.assertEqual(active.candidate_id, stalled.candidate_id)
        self.assertEqual(active.status, StrategyCandidateStatus.VALIDATING)
        self.assertEqual(active.cycles_without_progress, 0)
        self.assertIsNone(active.rejected_reason)

    def test_does_not_recover_candidate_rejected_for_a_different_stagnation_reason(self) -> None:
        mission = _market_wide_mission()
        genuinely_exhausted = _stagnant_candidate(mission, reason="sample_pool_exhausted_no_untried_robustness_symbol")
        mission = add_candidate(mission, genuinely_exhausted, now=_NOW)
        mission = record_blocked(
            mission,
            reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted",
            now=_NOW,
        )

        recovered, did_recover = attempt_bounded_stagnation_recovery(mission, now=_NOW)

        self.assertFalse(did_recover)
        self.assertEqual(recovered.status, MissionStatus.BLOCKED)
        self.assertEqual(
            recovered.blocked_reason,
            "strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted",
        )

    def test_scan_of_recoverable_reason_candidates_is_bounded_and_picks_the_first(self) -> None:
        mission = _market_wide_mission()
        first = _stagnant_candidate(mission, reason="validation_cycle_exhausted_without_progress")
        mission = add_candidate(mission, first, now=_NOW)
        second = _stagnant_candidate(mission, reason="validation_cycle_exhausted_without_progress")
        mission = add_candidate(mission, second, now=_NOW)
        mission = record_blocked(
            mission,
            reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted",
            now=_NOW,
        )

        recovered, did_recover = attempt_bounded_stagnation_recovery(mission, now=_NOW, max_candidates=1)

        # With the scan budget bounded to 1 recoverable-reason candidate,
        # only the first-encountered eligible candidate is ever reopened -
        # this must never grow into an unbounded scan across the whole
        # candidate portfolio.
        self.assertTrue(did_recover)
        active = get_active_candidate(recovered)
        self.assertEqual(active.candidate_id, first.candidate_id)


if __name__ == "__main__":
    unittest.main()
