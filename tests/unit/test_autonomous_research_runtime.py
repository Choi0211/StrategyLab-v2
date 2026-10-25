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
from gaon.knowledge.strategy_candidate import (
    ALL_STRATEGY_FAMILY_TEMPLATES,
    NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
    REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES,
    STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES,
    STRUCTURAL_FILTER_STRATEGY_FAMILY_TEMPLATES,
    StrategyCandidateStatus,
    new_candidate,
)
from gaon.runtime.autonomous_research_runtime import (
    AutonomousResearchTickResult,
    _next_interval_for_result,
    attempt_bounded_stagnation_recovery,
    attempt_bounded_strategy_space_recovery,
    ensure_autonomous_research_job,
    run_due_autonomous_research,
)
from gaon.runtime.migrations import migrate
from gaon.runtime.scheduled_automation import ScheduledJobRepository

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


class BoundedStrategySpaceRecoveryTests(unittest.TestCase):
    def test_blocked_mission_discovers_a_newly_deployed_structural_family(self) -> None:
        mission = _market_wide_mission()
        old_space = (
            *ALL_STRATEGY_FAMILY_TEMPLATES,
            *STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES,
            *NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
            *REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES,
        )
        for template in old_space:
            mission = add_candidate(
                mission,
                new_candidate(template.family, sequence=next_candidate_sequence(mission), now=_NOW),
                now=_NOW,
            )
        mission = record_blocked(
            mission,
            reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted",
            now=_NOW,
        )

        recovered, candidate, reason = attempt_bounded_strategy_space_recovery(mission, now=_NOW)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.strategy_family, STRUCTURAL_FILTER_STRATEGY_FAMILY_TEMPLATES[0].family)
        self.assertEqual(reason, "structural_filter_hypothesis_expansion")
        self.assertEqual(recovered.status, MissionStatus.ACTIVE)
        self.assertIsNone(recovered.blocked_reason)
        self.assertEqual(get_active_candidate(recovered).candidate_id, candidate.candidate_id)

    def test_unrelated_blocker_is_not_changed(self) -> None:
        mission = record_blocked(_market_wide_mission(), reason="provider_unavailable: fixture", now=_NOW)
        recovered, candidate, reason = attempt_bounded_strategy_space_recovery(mission, now=_NOW)
        self.assertIs(recovered, mission)
        self.assertIsNone(candidate)
        self.assertIsNone(reason)


class AutonomousResearchBackoffTests(unittest.TestCase):
    def test_unchanged_exhaustion_backs_off_to_six_hours(self) -> None:
        result = AutonomousResearchTickResult(attempted=True, action="hypothesis_value_space_exhausted")
        self.assertEqual(_next_interval_for_result(result, 900), 21600)

    def test_awaiting_evidence_backs_off_to_six_hours(self) -> None:
        result = AutonomousResearchTickResult(attempted=True, action="research_direction_awaiting_evidence")
        self.assertEqual(_next_interval_for_result(result, 900), 21600)

    def test_generic_blocked_state_backs_off_to_one_hour(self) -> None:
        result = AutonomousResearchTickResult(attempted=True, action="blocked_no_recovery")
        self.assertEqual(_next_interval_for_result(result, 900), 3600)


    def test_scheduler_persists_six_hour_next_run_after_unchanged_exhaustion(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        repo = ScheduledJobRepository(connection)
        now = "2026-10-17T12:00:00Z"
        self.assertTrue(ensure_autonomous_research_job(repo, now=now))

        class Worker:
            def tick(self):
                return AutonomousResearchTickResult(attempted=True, action="hypothesis_value_space_exhausted")

        results = run_due_autonomous_research(repo, Worker(), now=now)
        self.assertEqual(results[0].action, "hypothesis_value_space_exhausted")
        enabled = [job for job in repo.list() if job.enabled]
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].schedule.next_run_at, "2026-10-17T18:00:00Z")

    def test_scheduler_keeps_fifteen_minutes_after_progress(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        repo = ScheduledJobRepository(connection)
        now = "2026-10-17T12:00:00Z"
        self.assertTrue(ensure_autonomous_research_job(repo, now=now))

        class Worker:
            def tick(self):
                return AutonomousResearchTickResult(attempted=True, action="strategy_space_expanded")

        run_due_autonomous_research(repo, Worker(), now=now)
        enabled = [job for job in repo.list() if job.enabled]
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].schedule.next_run_at, "2026-10-17T12:15:00Z")

    def test_real_progress_keeps_normal_interval(self) -> None:
        for action in ("strategy_space_expanded", "candidate_created", "cycle_executed", "direction_evidence_acquired"):
            with self.subTest(action=action):
                result = AutonomousResearchTickResult(attempted=True, action=action)
                self.assertEqual(_next_interval_for_result(result, 900), 900)


    def test_crash_orphaned_tick_is_replaced_without_replaying_old_run(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        repo = ScheduledJobRepository(connection)
        old = "2026-10-24T00:00:00Z"
        now = "2026-10-25T00:00:00Z"
        self.assertTrue(ensure_autonomous_research_job(repo, now=old))
        job = next(j for j in repo.list() if j.enabled)
        run = repo.claim_run(job, now=old)
        self.assertIsNotNone(run)
        self.assertTrue(ensure_autonomous_research_job(repo, now=now))
        enabled = [j for j in repo.list() if j.enabled]
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].schedule.next_run_at, now)
        self.assertEqual(repo.list_runs(job.job_id)[0].status.value, "running")
        self.assertFalse(ensure_autonomous_research_job(repo, now=now))

    def test_recent_running_tick_is_not_recovered(self) -> None:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        repo = ScheduledJobRepository(connection)
        old = "2026-10-24T00:00:00Z"
        self.assertTrue(ensure_autonomous_research_job(repo, now=old))
        job = next(j for j in repo.list() if j.enabled)
        repo.claim_run(job, now=old)
        self.assertFalse(ensure_autonomous_research_job(repo, now="2026-10-24T00:30:00Z"))
        self.assertEqual(len([j for j in repo.list() if j.enabled]), 1)


if __name__ == "__main__":
    unittest.main()
