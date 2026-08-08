import unittest

from gaon.research.autonomous_completion import (
    AdaptiveResearchValidator,
    AdequacyStatus,
    AutonomousResearchGoal,
    AutonomousResearchCycleRequest,
    AutonomousResearchCycleRunner,
    AutonomousResearchPlanner,
    AutonomousLearningMemoryIntegrator,
    CycleTerminalState,
    OperationalAutonomousResearchRequest,
    OperationalAutonomousResearchRuntime,
    OperationalResearchRoute,
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
    gaon_autonomous_research_complete_release_check,
    gaon_autonomous_research_cycle_release_check,
    gaon_autonomous_research_planner_release_check,
    gaon_operational_autonomous_research_release_check,
    gaon_research_critic_release_check,
    gaon_strategy_candidate_generation_release_check,
    telegram_autonomous_research_payload,
)
from gaon.learning.repository import InMemoryLearningRepository
from gaon.runtime.storage import RuntimeStateStore


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


class AutonomousResearchCycleTests(unittest.TestCase):
    def test_cycle_persists_learning_and_stays_bounded(self) -> None:
        request = AutonomousResearchCycleRequest(
            run_id="cycle:test",
            symbol="005930",
            strategy_id="strategy:parent",
            evidence_payload={
                "metrics": {"trade_count": 3, "wins": 2, "losses": 1, "mdd": 0.12},
                "observation_days": 128,
                "market_regime_count": 1,
                "quality": {"status": "pass"},
                "evidence_refs": ("backtest:cycle",),
            },
            max_steps=5,
        )

        report = AutonomousResearchCycleRunner().run(request)

        self.assertEqual(report.terminal_state, CycleTerminalState.INSUFFICIENT_EVIDENCE)
        self.assertLessEqual(report.iterations, request.max_steps)
        self.assertIsNotNone(report.learning_report)
        self.assertFalse(report.to_json()["automatic_champion_promotion"])

    def test_cycle_fail_closed_on_invalid_quality(self) -> None:
        request = AutonomousResearchCycleRequest(
            run_id="cycle:invalid",
            symbol="005930",
            strategy_id="strategy:parent",
            evidence_payload={
                "metrics": {"trade_count": 3},
                "observation_days": 128,
                "market_regime_count": 1,
                "quality": {"status": "fail", "blocking_findings": 1},
                "evidence_refs": ("backtest:invalid",),
            },
        )

        report = AutonomousResearchCycleRunner().run(request)

        self.assertEqual(report.terminal_state, CycleTerminalState.DATA_FAILURE)

    def test_autonomous_research_cycle_release_check_passes(self) -> None:
        result = gaon_autonomous_research_cycle_release_check()

        self.assertEqual(result["safety"], "pass")

    def test_telegram_payload_uses_continuation_state_to_stop_duplicate_candidates(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            first = telegram_autonomous_research_payload(store._connection, "삼성전자 전략을 더 검증해봐", symbol="005930", mode="validate")
            state = {
                "current_cycle_id": first["run_id"],
                "root_cycle_id": first["run_id"],
                "continuation_count": 0,
                "tested_candidate_keys": first["progression"]["tested_candidate_keys"],
            }
            second = telegram_autonomous_research_payload(store._connection, "계속 연구해줘", symbol="005930", mode="continue", continuation_state=state)

            self.assertEqual(second["terminal_state"], "no_new_research_path")
            self.assertEqual(second["critic_report"]["retests"], [])
            self.assertEqual(second["progression"]["parent_cycle_id"], first["run_id"])
            self.assertEqual(second["progression"]["progression_state"], "NO_NEW_RESEARCH_PATH")
            self.assertTrue(second["progression"]["assumptions_immutable"])
            self.assertEqual(len(second["progression"]["historical_candidates"]), 2)
            self.assertEqual(len(second["progression"]["historical_tested_candidates"]), 2)
            self.assertEqual(second["progression"]["current_cycle_candidates"], [])
            self.assertEqual(len(second["progression"]["duplicate_candidates"]), 2)
            self.assertTrue(any("robust-breakout" in item for item in second["progression"]["historical_candidates"]))
            self.assertTrue(any("regime-filter" in item for item in second["progression"]["historical_candidates"]))
        finally:
            store.close()


class OperationalAutonomousResearchTests(unittest.TestCase):
    def _request(self, request_id: str = "operational:test", execute: bool = True) -> OperationalAutonomousResearchRequest:
        return OperationalAutonomousResearchRequest(
            request_id=request_id,
            user_message="삼성전자 자율 연구를 실행해줘",
            execute=execute,
            cycle_request=AutonomousResearchCycleRequest(
                run_id=request_id,
                symbol="005930",
                strategy_id="strategy:parent",
                evidence_payload={
                    "metrics": {"trade_count": 3, "wins": 2, "losses": 1, "mdd": 0.12},
                    "observation_days": 128,
                    "market_regime_count": 1,
                    "quality": {"status": "pass"},
                    "evidence_refs": ("backtest:operational",),
                },
            ),
        )

    def test_operational_runtime_routes_and_renders_korean_without_provider(self) -> None:
        response = OperationalAutonomousResearchRuntime().handle(self._request())

        self.assertEqual(response.route, OperationalResearchRoute.AUTONOMOUS_RESEARCH_CYCLE)
        self.assertIn("영하님", response.final_message)
        self.assertEqual(response.provider_calls, 0)

    def test_operational_runtime_skips_duplicate_request(self) -> None:
        runtime = OperationalAutonomousResearchRuntime()
        request = self._request()

        runtime.handle(request)
        duplicate = runtime.handle(request)

        self.assertEqual(duplicate.route, OperationalResearchRoute.DUPLICATE_SKIPPED)

    def test_operational_runtime_blocks_dry_run(self) -> None:
        response = OperationalAutonomousResearchRuntime().handle(self._request("operational:dry", execute=False))

        self.assertEqual(response.route, OperationalResearchRoute.SAFETY_BLOCKED)

    def test_operational_autonomous_research_release_check_passes(self) -> None:
        result = gaon_operational_autonomous_research_release_check()

        self.assertEqual(result["safety"], "pass")


class AutonomousResearchCompletionTests(unittest.TestCase):
    def test_complete_release_check_passes_all_component_checks(self) -> None:
        result = gaon_autonomous_research_complete_release_check()

        self.assertEqual(result["status"], "AUTONOMOUS RESEARCH COMPLETE")
        self.assertEqual(result["safety"], "pass")
        self.assertEqual(len(result["checks"]), 7)
        self.assertFalse(result["automatic_order"])
        self.assertFalse(result["automatic_champion_promotion"])
        self.assertFalse(result["automatic_config_apply"])


if __name__ == "__main__":
    unittest.main()
