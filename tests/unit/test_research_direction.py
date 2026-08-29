from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace

from gaon.knowledge.research_mission import add_candidate, extract_or_update_mission, record_blocked
from gaon.knowledge.strategy_candidate import StrategyCandidateStatus, new_candidate
from gaon.research.research_direction import (
    PROHIBITED_ACTIONS,
    FailureClass,
    NextResearchAction,
    ResearchDirectionRepository,
    ResearchDirectionStatus,
    analyze_mission_failure,
    classify_candidate_failure,
    mission_history_fingerprint,
    plan_research_direction,
)
from gaon.research.research_priority import propose_research_priority
from gaon.runtime.migrations import migrate

_NOW = "2026-08-29T00:00:00Z"


def _mission():
    return extract_or_update_mission(
        "국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요", existing=None, now=_NOW
    )


def _terminal_candidate(family: str, *, reason: str, status=StrategyCandidateStatus.REJECTED, sequence=1, stage_status=None):
    candidate = new_candidate(family, sequence=sequence, now=_NOW)
    return replace(
        candidate,
        status=status,
        rejected_reason=reason,
        validation_stage_status=stage_status or {},
    )


class ClassifyCandidateFailureTests(unittest.TestCase):
    def test_non_terminal_candidate_is_not_classified(self) -> None:
        candidate = new_candidate("breakout_standard", sequence=1, now=_NOW)
        self.assertIsNone(classify_candidate_failure(candidate))

    def test_user_requested_rotation_is_not_a_failure_signal(self) -> None:
        candidate = _terminal_candidate(
            "breakout_standard", reason="user_requested_different_strategy_family", status=StrategyCandidateStatus.STAGNANT
        )
        self.assertIsNone(classify_candidate_failure(candidate))

    def test_economic_viability_failure_reason_is_classified(self) -> None:
        candidate = _terminal_candidate(
            "breakout_standard", reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols"
        )
        self.assertEqual(classify_candidate_failure(candidate), FailureClass.ECONOMIC_VIABILITY_FAILURE)

    def test_validation_cycle_exhausted_without_progress_is_stagnation(self) -> None:
        candidate = _terminal_candidate(
            "breakout_standard", reason="validation_cycle_exhausted_without_progress", status=StrategyCandidateStatus.STAGNANT
        )
        self.assertEqual(classify_candidate_failure(candidate), FailureClass.VALIDATION_STAGNATION)

    def test_sample_pool_exhausted_reason_is_insufficient_sample(self) -> None:
        candidate = _terminal_candidate(
            "breakout_standard", reason="sample_pool_exhausted_no_untried_robustness_symbol", status=StrategyCandidateStatus.STAGNANT
        )
        self.assertEqual(classify_candidate_failure(candidate), FailureClass.INSUFFICIENT_SAMPLE)

    def test_provider_reason_is_data_provider_limitation(self) -> None:
        candidate = _terminal_candidate("breakout_standard", reason="provider_unavailable: no data source responded")
        self.assertEqual(classify_candidate_failure(candidate), FailureClass.DATA_PROVIDER_LIMITATION)

    def test_unrecognized_reason_with_sufficient_evidence_and_no_stage_failure_is_unknown(self) -> None:
        candidate = _terminal_candidate("breakout_standard", reason="some_future_reason_this_module_never_saw")
        candidate = replace(candidate, trade_count=999, attempted_symbols=10, valid_symbols=10)
        self.assertEqual(classify_candidate_failure(candidate), FailureClass.UNKNOWN)

    def test_unrecognized_reason_with_no_evidence_at_all_is_evidence_insufficiency(self) -> None:
        candidate = _terminal_candidate("breakout_standard", reason="some_future_reason_this_module_never_saw")
        self.assertEqual(classify_candidate_failure(candidate), FailureClass.EVIDENCE_INSUFFICIENCY)


class AnalyzeMissionFailureTests(unittest.TestCase):
    def test_breakdown_and_dominant_class_reflect_real_candidate_history(self) -> None:
        mission = _mission()
        mission = add_candidate(
            mission,
            _terminal_candidate("breakout_standard", reason="economic_viability_failed:x", sequence=1),
            now=_NOW,
        )
        mission = add_candidate(
            mission,
            _terminal_candidate("breakout_trend_confirmed", reason="economic_viability_failed:y", sequence=2),
            now=_NOW,
        )
        mission = add_candidate(
            mission,
            _terminal_candidate(
                "breakout_volume_confirmed", reason="validation_cycle_exhausted_without_progress",
                status=StrategyCandidateStatus.STAGNANT, sequence=3,
            ),
            now=_NOW,
        )
        mission = record_blocked(
            mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=_NOW
        )

        analysis = analyze_mission_failure(mission, session_ref="telegram:100", now=_NOW)

        self.assertEqual(analysis.breakdown[FailureClass.ECONOMIC_VIABILITY_FAILURE.value], 2)
        self.assertEqual(analysis.breakdown[FailureClass.VALIDATION_STAGNATION.value], 1)
        self.assertEqual(analysis.dominant_failure_class, FailureClass.ECONOMIC_VIABILITY_FAILURE)
        self.assertEqual(len(analysis.evidence_candidate_ids), 3)

    def test_fingerprint_is_deterministic_and_state_sensitive(self) -> None:
        mission = _mission()
        mission = add_candidate(mission, _terminal_candidate("breakout_standard", reason="economic_viability_failed:x"), now=_NOW)
        mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: x", now=_NOW)

        fingerprint_a = mission_history_fingerprint(mission, session_ref="telegram:100")
        fingerprint_b = mission_history_fingerprint(mission, session_ref="telegram:100")
        self.assertEqual(fingerprint_a, fingerprint_b, "identical mission state must yield an identical fingerprint")

        mission_changed = add_candidate(
            mission, _terminal_candidate("breakout_trend_confirmed", reason="economic_viability_failed:y", sequence=2), now=_NOW
        )
        fingerprint_c = mission_history_fingerprint(mission_changed, session_ref="telegram:100")
        self.assertNotEqual(fingerprint_a, fingerprint_c, "a changed candidate history must yield a different fingerprint")


class PlanResearchDirectionTests(unittest.TestCase):
    def _analysis_and_priority(self, mission):
        analysis = analyze_mission_failure(mission, session_ref="telegram:100", now=_NOW)
        priority = propose_research_priority(mission, None)
        return analysis, priority

    def test_no_recoverable_candidate_and_no_untried_family_waits_honestly(self) -> None:
        mission = _mission()
        mission = add_candidate(mission, _terminal_candidate("breakout_standard", reason="economic_viability_failed:x"), now=_NOW)
        mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: x", now=_NOW)
        analysis, priority = self._analysis_and_priority(mission)

        direction = plan_research_direction(
            analysis, priority, has_untried_family=False, has_recoverable_candidate=False, now=_NOW
        )

        self.assertEqual(direction.next_research_action, NextResearchAction.WAIT_FOR_REQUIRED_DATA)
        self.assertEqual(direction.status, ResearchDirectionStatus.AWAITING_EVIDENCE)
        self.assertIn("strategy_config_mutation", direction.prohibited_actions)
        self.assertIn("order_execution", direction.prohibited_actions)
        self.assertIn("champion_promotion", direction.prohibited_actions)
        self.assertIn("live_order_execution", direction.prohibited_actions)

    def test_untried_family_available_proposes_expansion_not_wait(self) -> None:
        mission = _mission()
        mission = add_candidate(mission, _terminal_candidate("breakout_standard", reason="economic_viability_failed:x"), now=_NOW)
        mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: x", now=_NOW)
        analysis, priority = self._analysis_and_priority(mission)

        direction = plan_research_direction(
            analysis, priority, has_untried_family=True, has_recoverable_candidate=False, now=_NOW
        )

        self.assertEqual(direction.next_research_action, NextResearchAction.EXPAND_HYPOTHESIS_FAMILY)
        self.assertEqual(direction.status, ResearchDirectionStatus.PROPOSED)

    def test_recoverable_candidate_available_proposes_robustness_not_wait(self) -> None:
        mission = _mission()
        mission = add_candidate(mission, _terminal_candidate("breakout_standard", reason="economic_viability_failed:x"), now=_NOW)
        mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: x", now=_NOW)
        analysis, priority = self._analysis_and_priority(mission)

        direction = plan_research_direction(
            analysis, priority, has_untried_family=False, has_recoverable_candidate=True, now=_NOW
        )

        self.assertEqual(direction.next_research_action, NextResearchAction.RUN_ROBUSTNESS_RESEARCH)
        self.assertEqual(direction.status, ResearchDirectionStatus.PROPOSED)

    def test_prohibited_actions_never_shrinks_the_sustainability_forbidden_list(self) -> None:
        from gaon.cognitive.sustainability import FORBIDDEN_JUSTIFICATIONS

        for justification in FORBIDDEN_JUSTIFICATIONS:
            self.assertIn(justification, PROHIBITED_ACTIONS)


class ResearchDirectionRepositoryIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.addCleanup(self.connection.close)

    def test_repeated_planning_against_unchanged_state_never_creates_duplicate_rows(self) -> None:
        mission = _mission()
        mission = add_candidate(mission, _terminal_candidate("breakout_standard", reason="economic_viability_failed:x"), now=_NOW)
        mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: x", now=_NOW)

        repository = ResearchDirectionRepository(self.connection)
        for _ in range(5):
            analysis = analyze_mission_failure(mission, session_ref="telegram:100", now=_NOW)
            priority = propose_research_priority(mission, None)
            direction = plan_research_direction(
                analysis, priority, has_untried_family=False, has_recoverable_candidate=False, now=_NOW
            )
            repository.put_failure_analysis(analysis)
            repository.put_direction(direction)

        self.assertEqual(repository.count_directions_for_session("telegram:100"), 1)
        row_count = self.connection.execute("SELECT COUNT(*) FROM research_failure_analyses").fetchone()[0]
        self.assertEqual(row_count, 1)


if __name__ == "__main__":
    unittest.main()
