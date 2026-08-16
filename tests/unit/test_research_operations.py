import sqlite3
import unittest

from gaon.research.operations import (
    DominanceDecision,
    QualityStatus,
    RecommendationDecision,
    ResearchOperationsService,
    SQLiteResearchOperationRepository,
    candidate_dominance,
    fixture_evidence_pair,
    research_period_policy,
    research_quality_gate,
    statistical_confidence,
)
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest, default_tool_registry
from gaon.runtime.migrations import migrate


NOW = "2026-07-26T00:00:00Z"


class ResearchOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.repository = SQLiteResearchOperationRepository(self.connection)
        self.service = ResearchOperationsService(self.repository)

    def tearDown(self) -> None:
        self.connection.close()

    def test_quality_gate_detects_insufficient_sample_and_period_expansion(self) -> None:
        _, challenger = fixture_evidence_pair(sufficient=False)

        quality = research_quality_gate(challenger, min_trades=30)
        period = research_period_policy(challenger, quality)
        confidence = statistical_confidence(challenger, quality)

        self.assertEqual(quality.status, QualityStatus.INSUFFICIENT_SAMPLE)
        self.assertTrue(period.expansion_required)
        self.assertEqual(period.status, "expand_and_retest")
        self.assertEqual(confidence.level.value, "low")

    def test_dominant_candidate_requires_quality_and_structured_metrics(self) -> None:
        champion, challenger = fixture_evidence_pair(sufficient=True)
        quality = research_quality_gate(challenger, min_trades=30)
        dominance = candidate_dominance(champion, challenger, quality)

        self.assertEqual(quality.status, QualityStatus.PASS)
        self.assertEqual(dominance.decision, DominanceDecision.DOMINATES)
        self.assertGreater(dominance.return_delta or 0.0, 0.02)

    def test_recommendation_does_not_change_config_without_approval(self) -> None:
        champion, challenger = fixture_evidence_pair(sufficient=True)
        report = self.service.analyze("research-ops:test", champion, challenger, generated_at=NOW)

        self.assertEqual(report.recommendation.decision, RecommendationDecision.RECOMMEND_CHALLENGER)
        self.assertIsNone(self.repository.active_config())
        self.assertTrue(report.recommendation.approval_required)

    def test_approval_applies_config_and_rollback_restores_previous(self) -> None:
        champion, challenger = fixture_evidence_pair(sufficient=True)
        first = self.service.analyze("research-ops:first", champion, challenger, generated_at=NOW)
        first_config = self.service.approve_and_apply(first.report_id, actor_ref="human:youngha", approved_at="2026-07-26T00:01:00Z")
        second = self.service.analyze("research-ops:second", champion, challenger, generated_at="2026-07-26T00:02:00Z")
        second_config = self.service.approve_and_apply(second.report_id, actor_ref="human:youngha", approved_at="2026-07-26T00:03:00Z")

        rolled_back = self.service.rollback(second_config.config_id, actor_ref="human:youngha", rolled_back_at="2026-07-26T00:04:00Z")

        self.assertEqual(first_config.strategy_ref, rolled_back.strategy_ref)
        self.assertEqual(rolled_back.previous_config_id, second_config.config_id)
        self.assertGreaterEqual(len(self.repository.audit_history()), 5)

    def test_fixture_evidence_cannot_drive_config_change(self) -> None:
        champion, challenger = fixture_evidence_pair(sufficient=True)
        fixture_challenger = type(challenger)(
            challenger.result_id,
            challenger.strategy_ref,
            challenger.period_start,
            challenger.period_end,
            "fixture",
            True,
            challenger.metrics,
            challenger.quality_status,
            challenger.provider_gap_count,
            challenger.blocking_findings,
        )

        report = self.service.analyze("research-ops:fixture", champion, fixture_challenger, generated_at=NOW)

        self.assertEqual(report.quality_gate.status, QualityStatus.FAIL)
        self.assertNotEqual(report.recommendation.decision, RecommendationDecision.RECOMMEND_CHALLENGER)

    def test_research_operation_status_tool_is_read_only(self) -> None:
        champion, challenger = fixture_evidence_pair(sufficient=True)
        self.service.analyze("research-ops:tool", champion, challenger, generated_at=NOW)
        executor = SafeToolExecutor(default_tool_registry(self.connection))

        result = executor.execute(ToolRequest("research_operation_status", {"limit": 3}, "unit", NOW))

        self.assertEqual(result.status, "success")
        self.assertFalse(result.output["automatic_order"])
        self.assertFalse(result.output["automatic_champion_promotion"])
        self.assertEqual(result.output["provider"], "sqlite:research_operations")

    def test_release_check_artifacts_are_hidden_from_status_tool(self) -> None:
        champion, challenger = fixture_evidence_pair(sufficient=True)
        self.service.analyze("research-ops-release-check:unit", champion, challenger, generated_at=NOW)
        executor = SafeToolExecutor(default_tool_registry(self.connection))

        result = executor.execute(ToolRequest("research_operation_status", {"limit": 3}, "unit", NOW))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output["reports"], [])
        self.assertTrue(result.output["empty"])
        self.assertIn("현재 활성 연구 운영 결과가 없습니다", result.output["message"])

    def test_cleanup_dry_run_and_apply_only_target_artifacts(self) -> None:
        champion, challenger = fixture_evidence_pair(sufficient=True)
        artifact = self.service.analyze("research-ops-release-check:cleanup", champion, challenger, generated_at=NOW)
        self.service.approve_and_apply(artifact.report_id, actor_ref="release-check-human", approved_at="2026-07-26T00:01:00Z")
        real = self.service.analyze("research-ops:user-live", champion, challenger, generated_at="2026-07-26T00:02:00Z")

        dry_run = self.repository.cleanup_artifacts(apply=False, actor_ref="unit", created_at="2026-07-26T00:03:00Z")
        self.assertGreater(dry_run.total, 0)
        self.assertIsNotNone(self.repository.get_report(artifact.report_id))

        applied = self.repository.cleanup_artifacts(apply=True, actor_ref="unit", created_at="2026-07-26T00:04:00Z")

        self.assertEqual(applied.report_ids, dry_run.report_ids)
        self.assertIsNone(self.repository.get_report(artifact.report_id))
        self.assertIsNotNone(self.repository.get_report(real.report_id))
        self.assertTrue(any(item["event_type"] == "artifact_cleanup" for item in self.repository.audit_history()))
        self.assertIsNone(self.repository.active_config())

    def test_real_research_report_and_config_remain_visible(self) -> None:
        champion, challenger = fixture_evidence_pair(sufficient=True)
        report = self.service.analyze("research-ops:user-visible", champion, challenger, generated_at=NOW)
        config = self.service.approve_and_apply(report.report_id, actor_ref="human:youngha", approved_at="2026-07-26T00:01:00Z")

        self.assertEqual(self.repository.list_reports()[-1]["report_id"], report.report_id)
        self.assertEqual(self.repository.active_config().config_id, config.config_id)


if __name__ == "__main__":
    unittest.main()
