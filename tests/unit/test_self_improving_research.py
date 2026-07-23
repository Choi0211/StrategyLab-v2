import sqlite3
import unittest

from gaon.research.self_improving import (
    AutonomousResearchOrchestrator,
    AutonomousResearchRequest,
    CritiqueDecision,
    CritiqueSeverity,
    NoveltyStatus,
    ResearchCritic,
    ResearchIterationLoop,
    ResearchKnowledgeBase,
    ResearchConcept,
    ResearchEvidence,
    ConceptRelationship,
    ConceptRelationshipType,
    ResearchNoveltyDetector,
    ResearchQualityScorer,
    ResearchTournamentRunner,
    SQLiteResearchMemoryRepository,
    StrategyImprovementPlanner,
    build_memory_entry,
    candidate_fingerprint,
    fixture_candidate,
    fixture_candidates,
)
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, ToolRequest, default_tool_registry
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


NOW = "2026-07-24T00:00:00Z"


class ResearchSelfCriticTests(unittest.TestCase):
    def test_clean_candidate_passes(self) -> None:
        critique = ResearchCritic().evaluate(fixture_candidate("strong"), created_at=NOW)
        self.assertIn(critique.decision, {CritiqueDecision.PASS, CritiqueDecision.PASS_WITH_WARNINGS})

    def test_overfit_candidate_is_rejected(self) -> None:
        critique = ResearchCritic().evaluate(fixture_candidate("overfit"), created_at=NOW)
        self.assertEqual(critique.decision, CritiqueDecision.REJECT)
        self.assertIn("overfit_gap", {finding.code for finding in critique.findings})

    def test_high_mdd_low_sample_unstable_wf_fragile_and_regime_findings(self) -> None:
        scenarios = {
            "high_mdd": "high_mdd",
            "low_sample": "weak_sample",
            "unstable_wf": "wf_instability",
            "fragile": "mc_fragility",
            "regime_dependent": "regime_dependency",
        }
        for scenario, code in scenarios.items():
            with self.subTest(scenario=scenario):
                critique = ResearchCritic().evaluate(fixture_candidate(scenario), created_at=NOW)
                self.assertIn(code, {finding.code for finding in critique.findings})

    def test_improvement_plan_is_traceable_and_supported(self) -> None:
        candidate = fixture_candidate("overfit")
        critique = ResearchCritic().evaluate(candidate, created_at=NOW)
        plan = StrategyImprovementPlanner().plan(candidate, critique, created_at=NOW)
        self.assertTrue(plan.actions)
        self.assertFalse(plan.unsupported_mutations)
        self.assertLessEqual({action.finding_code for action in plan.actions}, {finding.code for finding in critique.findings})

    def test_iteration_loop_stops_at_max_and_preserves_lineage(self) -> None:
        final, _critique, _plan, quality, iterations = ResearchIterationLoop().run(fixture_candidate("overfit"), run_id="unit-loop", max_iterations=3, created_at=NOW)
        self.assertLessEqual(len(iterations), 3)
        self.assertIsNotNone(final.parent_strategy_id)
        self.assertGreaterEqual(final.generation, 1)
        self.assertGreaterEqual(quality.total, 0.0)

    def test_quality_score_range_components_and_weights(self) -> None:
        candidate = fixture_candidate("balanced")
        critique = ResearchCritic().evaluate(candidate, created_at=NOW)
        quality = ResearchQualityScorer().score(candidate, critique, created_at=NOW)
        self.assertGreaterEqual(quality.total, 0)
        self.assertLessEqual(quality.total, 100)
        self.assertEqual(set(quality.components), set(ResearchQualityScorer.DEFAULT_WEIGHTS))
        with self.assertRaises(ValueError):
            ResearchQualityScorer({"performance": 1.0})

    def test_tournament_ranks_eliminates_and_returns_top_n(self) -> None:
        tournament = ResearchTournamentRunner().run(fixture_candidates(6), top_n=2, created_at=NOW)
        self.assertEqual(len(tournament.top_n), 2)
        self.assertEqual(tuple(rank.rank for rank in tournament.rankings), tuple(range(1, len(tournament.rankings) + 1)))
        self.assertTrue(any(item.eliminated for item in tournament.rankings))

    def test_memory_duplicate_fingerprint_and_filters(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        repository = SQLiteResearchMemoryRepository(connection)
        candidate = fixture_candidate("balanced")
        critique = ResearchCritic().evaluate(candidate, created_at=NOW)
        plan = StrategyImprovementPlanner().plan(candidate, critique, created_at=NOW)
        quality = ResearchQualityScorer().score(candidate, critique, created_at=NOW)
        entry = build_memory_entry(candidate, critique, plan, quality, run_id="unit-memory", created_at=NOW)
        repository.add_memory(entry)
        with self.assertRaises(sqlite3.IntegrityError):
            repository.add_memory(entry)
        self.assertEqual(repository.find_by_fingerprint(candidate_fingerprint(candidate)).memory_id, entry.memory_id)  # type: ignore[union-attr]
        self.assertEqual(len(repository.search(strategy_family="breakout", market="KRX", timeframe="daily")), 1)
        self.assertEqual(len(repository.search(query="overfit_gap")), 0)

    def test_novelty_detection(self) -> None:
        candidate = fixture_candidate("balanced")
        critique = ResearchCritic().evaluate(candidate, created_at=NOW)
        plan = StrategyImprovementPlanner().plan(candidate, critique, created_at=NOW)
        quality = ResearchQualityScorer().score(candidate, critique, created_at=NOW)
        memory = build_memory_entry(candidate, critique, plan, quality, run_id="unit-memory", created_at=NOW)
        self.assertEqual(ResearchNoveltyDetector().detect(candidate, (memory,)), NoveltyStatus.EXACT_DUPLICATE)
        similar = fixture_candidate("strong", family=candidate.family, market=candidate.market, timeframe=candidate.timeframe, hypothesis="Use pullback continuation with risk filters.")
        self.assertEqual(ResearchNoveltyDetector().detect(similar, (memory,)), NoveltyStatus.SIMILAR_FAMILY)

    def test_knowledge_base_requires_evidence(self) -> None:
        kb = ResearchKnowledgeBase()
        with self.assertRaises(ValueError):
            kb.add_concept(ResearchConcept("c1", "breakout", "desc", (), NOW))
        kb.add_concept(ResearchConcept("c1", "breakout", "desc", ("fixture:evidence",), NOW))
        evidence = ResearchEvidence("e1", "fixture:evidence", "summary", "fixture", NOW)
        relationship = ConceptRelationship("r1", "c1", ConceptRelationshipType.SUPPORTS, evidence.evidence_id, (evidence.evidence_id,), NOW)
        kb.add_relationship(relationship)
        self.assertEqual(kb.related("c1"), (relationship,))

    def test_orchestrator_full_flow_saves_memory_and_preserves_safety(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        repository = SQLiteResearchMemoryRepository(connection)
        request = AutonomousResearchRequest("req-1", "KRX", "daily", "breakout", "Improve volume breakout")
        result = AutonomousResearchOrchestrator(repository).run(request, run_id="unit-auto", created_at=NOW)
        self.assertIsNotNone(result.memory_id)
        self.assertFalse(result.critique.automatic_promotion)
        self.assertIn("no code", " ".join(result.warnings))
        duplicate = AutonomousResearchOrchestrator(repository).run(request, run_id="unit-auto-2", created_at=NOW)
        self.assertIsNone(duplicate.memory_id)
        self.assertIn("duplicate", " ".join(duplicate.warnings))

    def test_safe_tools_are_read_only_and_audited(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        executor = SafeToolExecutor(default_tool_registry(connection), SQLiteToolAuditRepository(connection))
        result = executor.execute(ToolRequest("strategy_critique", {"scenario": "overfit"}, "unit", NOW))
        self.assertEqual(result.status, "success")
        self.assertEqual(result.output["automatic_promotion"], False)
        audit = SQLiteToolAuditRepository(connection).list(tool_name="strategy_critique")
        self.assertEqual(audit[0].risk_level, "read_only")
        denied = executor.execute(ToolRequest("strategy_critique", {"scenario": "overfit", "sql": "select 1"}, "unit", NOW))
        self.assertEqual(denied.status, "denied")

    def test_schema_version_increments_to_self_improving_tables(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        self.assertGreaterEqual(SCHEMA_VERSION, 31)
        row = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='research_memories'").fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
