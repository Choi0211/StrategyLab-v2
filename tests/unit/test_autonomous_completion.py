import unittest

from gaon.research.autonomous_completion import (
    AdaptiveResearchValidator,
    AdequacyStatus,
    AutonomousResearchGoal,
    AutonomousResearchPlanner,
    AutonomousLearningMemoryIntegrator,
    CriticImprovementRetestLoop,
    ResearchBudget,
    ResearchCriticEngine,
    ResearchStopCondition,
    ResearchStepKind,
    StrategyCandidateGenerator,
    StrategyCandidateStatus,
    ValidationNeedKind,
    ValidationStopReason,
    gaon_adaptive_validation_release_check,
    gaon_autonomous_learning_memory_release_check,
    gaon_autonomous_research_planner_release_check,
    gaon_research_critic_release_check,
    gaon_strategy_candidate_generation_release_check,
)
from gaon.learning.repository import InMemoryLearningRepository


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


class AutonomousResearchPlannerTests(unittest.TestCase):
    def test_planner_builds_bounded_steps_from_validation_needs(self) -> None:
        assessment = AdaptiveResearchValidator().assess(
            {
                "metrics": {"trade_count": 1, "wins": 1, "losses": 0},
                "observation_days": 100,
                "market_regime_count": 1,
                "quality": {"status": "pass"},
                "evidence_refs": ("assessment:1",),
            }
        )
        goal = AutonomousResearchGoal("goal:1", "validate strategy", ("005930",), assessment.evidence_refs)
        plan = AutonomousResearchPlanner(ResearchBudget(3, 1, 60)).plan(goal, assessment)

        self.assertLessEqual(len(plan.steps), 3)
        self.assertIn(ResearchStopCondition.MAX_STEPS_REACHED, plan.stop_conditions)
        self.assertEqual(plan.steps[0].kind, ResearchStepKind.EXTEND_PERIOD)
        self.assertFalse(plan.to_json()["automatic_config_apply"])

    def test_planner_stops_on_invalid_data(self) -> None:
        assessment = AdaptiveResearchValidator().assess({"metrics": {"trade_count": 50}, "quality": {"status": "fail", "missing_bar_count": 1}})
        plan = AutonomousResearchPlanner().plan(AutonomousResearchGoal("goal:bad", "bad data", ("005930",), ()), assessment)

        self.assertEqual(plan.stop_conditions, (ResearchStopCondition.DATA_FAILURE,))
        self.assertEqual(plan.terminal_if_unresolved, "data_failure")

    def test_planner_release_check_passes(self) -> None:
        result = gaon_autonomous_research_planner_release_check()

        self.assertEqual(result["safety"], "pass")


class StrategyCandidateGenerationTests(unittest.TestCase):
    def test_candidates_are_proposed_and_do_not_mutate_production(self) -> None:
        assessment = AdaptiveResearchValidator().assess(
            {
                "metrics": {"trade_count": 1, "wins": 1, "losses": 0},
                "observation_days": 100,
                "market_regime_count": 1,
                "quality": {"status": "pass"},
                "evidence_refs": ("assessment:1",),
            }
        )
        goal = AutonomousResearchGoal("goal:candidate", "candidate generation", ("005930",), assessment.evidence_refs)
        plan = AutonomousResearchPlanner().plan(goal, assessment)
        candidates = StrategyCandidateGenerator().generate("strategy:parent", assessment, plan)

        self.assertTrue(candidates)
        self.assertTrue(all(candidate.status is StrategyCandidateStatus.PROPOSED for candidate in candidates if candidate.changed_rules))
        self.assertFalse(any(candidate.production_mutation_allowed for candidate in candidates))
        self.assertTrue(all(candidate.supporting_evidence for candidate in candidates))

    def test_candidate_release_check_passes(self) -> None:
        result = gaon_strategy_candidate_generation_release_check()

        self.assertEqual(result["safety"], "pass")


class ResearchCriticRetestTests(unittest.TestCase):
    def test_critic_flags_sample_size_and_drawdown(self) -> None:
        assessment = AdaptiveResearchValidator().assess(
            {
                "metrics": {"trade_count": 1, "wins": 1, "losses": 0, "mdd": 0.3},
                "observation_days": 100,
                "market_regime_count": 1,
                "quality": {"status": "pass"},
                "evidence_refs": ("backtest:critic",),
            }
        )

        findings = ResearchCriticEngine().critique(assessment)

        self.assertIn("sample_size", {finding.category for finding in findings})
        self.assertIn("drawdown", {finding.category for finding in findings})

    def test_critic_loop_preserves_retests_and_no_mutation(self) -> None:
        assessment = AdaptiveResearchValidator().assess(
            {
                "metrics": {"trade_count": 1, "wins": 1, "losses": 0, "mdd": 0.25},
                "observation_days": 100,
                "market_regime_count": 1,
                "quality": {"status": "pass"},
                "evidence_refs": ("backtest:critic",),
            }
        )
        goal = AutonomousResearchGoal("goal:critic", "critic loop", ("005930",), assessment.evidence_refs)
        plan = AutonomousResearchPlanner().plan(goal, assessment)
        report = CriticImprovementRetestLoop().run("strategy:parent", assessment, plan)

        self.assertTrue(report.proposals)
        self.assertTrue(report.retests)
        self.assertFalse(report.to_json()["automatic_config_apply"])

    def test_research_critic_release_check_passes(self) -> None:
        result = gaon_research_critic_release_check()

        self.assertEqual(result["safety"], "pass")


class AutonomousLearningMemoryIntegrationTests(unittest.TestCase):
    def test_integrator_stores_evidence_backed_unvalidated_record(self) -> None:
        assessment = AdaptiveResearchValidator().assess(
            {
                "metrics": {"trade_count": 2, "wins": 1, "losses": 1, "mdd": 0.1},
                "observation_days": 128,
                "market_regime_count": 1,
                "quality": {"status": "pass"},
                "evidence_refs": ("backtest:learning",),
            }
        )
        plan = AutonomousResearchPlanner().plan(AutonomousResearchGoal("goal:learning", "learn", ("005930",), assessment.evidence_refs), assessment)
        critic_report = CriticImprovementRetestLoop().run("strategy:parent", assessment, plan)
        repository = InMemoryLearningRepository()

        report = AutonomousLearningMemoryIntegrator().integrate("run:learning", critic_report, repository)

        self.assertEqual(len(report.stored_records), 1)
        self.assertEqual(len(repository.list_all()), 1)
        self.assertEqual(len(repository.list_audit()), 1)
        self.assertFalse(report.knowledge_validated)
        self.assertFalse(report.policy_applied)

    def test_integrator_reports_duplicate_without_merge(self) -> None:
        assessment = AdaptiveResearchValidator().assess(
            {
                "metrics": {"trade_count": 2, "wins": 1, "losses": 1, "mdd": 0.1},
                "observation_days": 128,
                "market_regime_count": 1,
                "quality": {"status": "pass"},
                "evidence_refs": ("backtest:learning",),
            }
        )
        plan = AutonomousResearchPlanner().plan(AutonomousResearchGoal("goal:learning", "learn", ("005930",), assessment.evidence_refs), assessment)
        critic_report = CriticImprovementRetestLoop().run("strategy:parent", assessment, plan)
        repository = InMemoryLearningRepository()
        integrator = AutonomousLearningMemoryIntegrator()

        integrator.integrate("run:learning", critic_report, repository)
        duplicate = integrator.integrate("run:learning", critic_report, repository)

        self.assertEqual(len(repository.list_all()), 1)
        self.assertEqual(duplicate.duplicate_candidates, ("autonomous-learning:run:learning:research-outcome",))

    def test_autonomous_learning_memory_release_check_passes(self) -> None:
        result = gaon_autonomous_learning_memory_release_check()

        self.assertEqual(result["safety"], "pass")


if __name__ == "__main__":
    unittest.main()
