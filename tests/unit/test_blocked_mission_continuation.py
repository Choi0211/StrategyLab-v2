"""Regression tests for feature/gaon-autonomous-blocked-research-next-step.

Context: a durable market-wide KR/KOSPI+KOSDAQ/short_term_daytrade
ResearchMission structurally BLOCKED on ``strategy_hypothesis_space_
exhausted`` used to have every live-conversation continuation request
("단타 연구해주세요", "계속 연구해주세요", "부족한 부분을 채워주세요")
short-circuit straight to the same static, always-identical blocked
explanation - never attempting the bounded stagnation-recovery path, and
never running the evidence-grounded FAILURE ANALYSIS -> RESEARCH PRIORITY
-> RESEARCH DIRECTION diagnosis the background autonomous-research tick
already performs for exactly this dead end (Hotfix #168/#169). This module
(``gaon.runtime.gaon_agent.blocked_mission_continuation``) closes that gap
by reusing both of those existing pieces of machinery directly.

These are unit tests against the module's pure functions - the full
conversational wiring (``LLMConversationBrain._try_mission_driven_research_
cycle`` / ``_try_gap_analysis`` / ``gaon.runtime.research_grounding.
safe_capability_reply``) is covered separately in
``tests/integration/test_gaon_autonomous_blocked_research_next_step.py``.
"""

from __future__ import annotations

import sqlite3
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
from gaon.runtime.gaon_agent.blocked_mission_continuation import (
    attempt_structural_blocker_autonomous_continuation,
    diagnose_structural_blocker,
    is_structural_hypothesis_space_blocker,
)
from gaon.runtime.migrations import migrate

_NOW = "2026-08-22T00:00:05Z"
_STRUCTURAL_REASON = "strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted"
_MISSION_SEED_TEXT = "국내 주식 전체(코스피+코스닥)를 대상으로 단타 전략을 연구해주세요. 승격 가능한 후보 3개까지."


def _market_wide_mission():
    return extract_or_update_mission(_MISSION_SEED_TEXT, existing=None, now=_NOW)


def _stagnant_candidate(mission, *, reason: str):
    candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=_NOW)
    return replace(candidate, status=StrategyCandidateStatus.STAGNANT, rejected_reason=reason, cycles_without_progress=5)


def _rejected_candidate(mission, *, family: str, sequence: int, reason: str):
    candidate = new_candidate(family, sequence=sequence, now=_NOW)
    return replace(candidate, status=StrategyCandidateStatus.REJECTED, rejected_reason=reason)


class IsStructuralHypothesisSpaceBlockerTests(unittest.TestCase):
    def test_true_for_the_exact_structural_reason(self) -> None:
        mission = record_blocked(_market_wide_mission(), reason=_STRUCTURAL_REASON, now=_NOW)
        self.assertTrue(is_structural_hypothesis_space_blocker(mission))

    def test_false_for_an_active_mission(self) -> None:
        mission = _market_wide_mission()
        self.assertIs(mission.status, MissionStatus.ACTIVE)
        self.assertFalse(is_structural_hypothesis_space_blocker(mission))

    def test_false_for_selected_symbol_universe_exhausted(self) -> None:
        mission = record_blocked(_market_wide_mission(), reason="selected_symbol_universe_exhausted", now=_NOW)
        self.assertFalse(is_structural_hypothesis_space_blocker(mission))

    def test_false_for_a_transient_provider_blocker(self) -> None:
        mission = record_blocked(
            _market_wide_mission(), reason="provider_acquisition_blocker: symbol=005930,category=timeout", now=_NOW
        )
        self.assertFalse(is_structural_hypothesis_space_blocker(mission))

    def test_false_for_an_unrelated_dynamic_reason(self) -> None:
        mission = record_blocked(_market_wide_mission(), reason="provider_unavailable: no data source responded", now=_NOW)
        self.assertFalse(is_structural_hypothesis_space_blocker(mission))


class AttemptStructuralBlockerAutonomousContinuationRecoveryTests(unittest.TestCase):
    """When a real, narrow-recovery-eligible candidate exists, the mission
    must be reactivated (the existing safe research continuation path),
    never left at a static "you are blocked" text."""

    def test_recovers_a_stalled_candidate_and_never_returns_a_message(self) -> None:
        mission = _market_wide_mission()
        stalled = _stagnant_candidate(mission, reason="validation_cycle_exhausted_without_progress")
        mission = add_candidate(mission, stalled, now=_NOW)
        mission = record_blocked(mission, reason=_STRUCTURAL_REASON, now=_NOW)

        outcome = attempt_structural_blocker_autonomous_continuation(
            mission, session_id="telegram:100", connection=None, now=_NOW
        )

        self.assertIsNone(outcome.message)
        self.assertIsNotNone(outcome.recovered_mission)
        self.assertIs(outcome.recovered_mission.status, MissionStatus.ACTIVE)
        self.assertIsNone(outcome.recovered_mission.blocked_reason)
        active = get_active_candidate(outcome.recovered_mission)
        self.assertIsNotNone(active)
        self.assertEqual(active.candidate_id, stalled.candidate_id)

    def test_recovery_never_persists_anything_even_with_a_real_connection(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        mission = _market_wide_mission()
        stalled = _stagnant_candidate(mission, reason="validation_cycle_exhausted_without_progress")
        mission = add_candidate(mission, stalled, now=_NOW)
        mission = record_blocked(mission, reason=_STRUCTURAL_REASON, now=_NOW)

        attempt_structural_blocker_autonomous_continuation(
            mission, session_id="telegram:100", connection=connection, now=_NOW
        )

        self.assertEqual(connection.execute("SELECT COUNT(*) FROM research_directions").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM research_failure_analyses").fetchone()[0], 0)


class AttemptStructuralBlockerAutonomousContinuationDiagnosisTests(unittest.TestCase):
    """When no safe recovery candidate exists, Gaon must state a concrete,
    evidence-grounded next step - never the old generic always-identical
    canned sentence, never a raw internal blocker code, and never a
    request asking the human to pick a direction."""

    def _exhausted_mission_with_dominant_class(self, *, reason: str):
        mission = _market_wide_mission()
        # Two terminal candidates sharing the same classifiable rejection
        # reason so analyze_mission_failure has an unambiguous dominant
        # failure class to report (see gaon.research.research_direction.
        # classify_candidate_failure).
        first = _rejected_candidate(mission, family="breakout_standard", sequence=1, reason=reason)
        mission = add_candidate(mission, first, now=_NOW)
        second = _rejected_candidate(mission, family="breakout_trend_confirmed", sequence=2, reason=reason)
        mission = add_candidate(mission, second, now=_NOW)
        return record_blocked(mission, reason=_STRUCTURAL_REASON, now=_NOW)

    def test_no_recovery_candidate_returns_a_diagnosis_message_not_a_mission(self) -> None:
        mission = self._exhausted_mission_with_dominant_class(
            reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols"
        )
        outcome = attempt_structural_blocker_autonomous_continuation(
            mission, session_id="telegram:100", connection=None, now=_NOW
        )
        self.assertIsNone(outcome.recovered_mission)
        self.assertIsNotNone(outcome.message)

    def test_diagnosis_never_leaks_the_raw_blocker_code(self) -> None:
        mission = self._exhausted_mission_with_dominant_class(
            reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols"
        )
        message = diagnose_structural_blocker(mission, session_id="telegram:100", now=_NOW)
        self.assertNotIn("strategy_hypothesis_space_exhausted", message)

    def test_diagnosis_never_asks_the_user_to_choose_a_direction(self) -> None:
        mission = self._exhausted_mission_with_dominant_class(
            reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols"
        )
        message = diagnose_structural_blocker(mission, session_id="telegram:100", now=_NOW)
        # The old dead end always left the choice to the human ("어떤
        # 시장/전략 스타일로 연구를 시작할지 알려주시면..."); the new
        # diagnosis states what Gaon itself determined instead.
        self.assertNotIn("알려주시면", message)
        self.assertIn("지금 안전하게 자동으로 실행할 수 있는 추가 조치는 없으며", message)

    def test_dominant_failure_class_reflects_the_real_candidate_history(self) -> None:
        mission = self._exhausted_mission_with_dominant_class(
            reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols"
        )
        message = diagnose_structural_blocker(mission, session_id="telegram:100", now=_NOW)
        self.assertIn("경제성(수익성) 검증 실패", message)

        other_mission = self._exhausted_mission_with_dominant_class(reason="sample_pool_exhausted_no_untried_robustness_symbol")
        other_message = diagnose_structural_blocker(other_mission, session_id="telegram:100", now=_NOW)
        self.assertIn("표본 부족", other_message)
        self.assertNotEqual(message, other_message)

    def test_diagnosis_persists_an_idempotent_direction_and_analysis_row(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        mission = self._exhausted_mission_with_dominant_class(
            reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols"
        )

        first = attempt_structural_blocker_autonomous_continuation(
            mission, session_id="telegram:100", connection=connection, now=_NOW
        )
        second = attempt_structural_blocker_autonomous_continuation(
            mission, session_id="telegram:100", connection=connection, now=_NOW
        )

        self.assertIsNone(first.recovered_mission)
        self.assertEqual(first.message, second.message)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM research_directions").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM research_failure_analyses").fetchone()[0], 1)

    def test_no_candidate_history_at_all_still_renders_an_honest_diagnosis(self) -> None:
        # A degenerate fixture shape (forced BLOCKED with zero candidates
        # ever attempted) must still degrade gracefully, never crash and
        # never fabricate evidence that does not exist.
        mission = record_blocked(_market_wide_mission(), reason=_STRUCTURAL_REASON, now=_NOW)
        message = diagnose_structural_blocker(mission, session_id="telegram:100", now=_NOW)
        self.assertIn("전략 가설군(bounded grammar) 소진", message)
        self.assertNotIn("strategy_hypothesis_space_exhausted", message)


if __name__ == "__main__":
    unittest.main()
