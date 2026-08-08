from __future__ import annotations

import unittest

from gaon.knowledge.conflicts import ConflictStatus
from gaon.knowledge.discovery import (
    DiscoveryBudget,
    DiscoveryPolicy,
    DiscoveryProvider,
    SourceDiscoveryPlanner,
    canonical_query_id,
    discovery_release_check,
)
from gaon.knowledge.gaps import (
    KnowledgeGapType,
    RequiredEvidence,
    RequiredEvidenceType,
    ResearchPriority,
    ResearchQuestion,
    ResearchStopCondition,
)
from gaon.knowledge.provenance import SourceType


def make_question(
    gap_type: KnowledgeGapType,
    *,
    question_id: str = "research-question:test",
) -> ResearchQuestion:
    source_state = {
        KnowledgeGapType.CONTRADICTION:
            ConflictStatus.UNRESOLVED_CONFLICT,
        KnowledgeGapType.INSUFFICIENT_INDEPENDENCE:
            ConflictStatus.INSUFFICIENT_INDEPENDENCE,
        KnowledgeGapType.MISSING_DIRECTIONAL_EVIDENCE:
            ConflictStatus.NO_COMPARABLE_EVIDENCE,
    }[gap_type]

    return ResearchQuestion(
        question_id=question_id,
        topic_key="trend.regime.robustness",
        gap_type=gap_type,
        question="Test research question",
        priority=(
            ResearchPriority.HIGH
            if gap_type is KnowledgeGapType.CONTRADICTION
            else ResearchPriority.MEDIUM
        ),
        required_evidence=(
            RequiredEvidence(
                evidence_type=
                    RequiredEvidenceType.INDEPENDENT_PRIMARY_SOURCE,
                minimum_independent_sources=1,
                rationale="test evidence",
            ),
        ),
        stop_conditions=(
            ResearchStopCondition.EVIDENCE_BUDGET_EXHAUSTED,
        ),
        parent_conflict_id="knowledge-conflict:test",
        source_state=source_state,
    )


class SourceDiscoveryTests(unittest.TestCase):
    def test_query_id_is_deterministic(self) -> None:
        first = canonical_query_id(
            question_id="research-question:test",
            provider=DiscoveryProvider.ACADEMIC_SEARCH,
            query="trend regime robustness",
        )
        second = canonical_query_id(
            question_id="research-question:test",
            provider=DiscoveryProvider.ACADEMIC_SEARCH,
            query="trend   regime robustness",
        )
        self.assertEqual(first, second)

    def test_contradiction_builds_bounded_plan(self) -> None:
        plan = SourceDiscoveryPlanner().build(
            make_question(
                KnowledgeGapType.CONTRADICTION
            )
        )

        self.assertGreater(len(plan.queries), 0)
        self.assertLessEqual(
            len(plan.queries),
            plan.budget.max_queries,
        )
        self.assertFalse(plan.network_executed)

    def test_policy_filters_disallowed_provider(self) -> None:
        policy = DiscoveryPolicy(
            allowed_source_types=(
                SourceType.OFFICIAL_DOCUMENT,
            ),
            allowed_providers=(
                DiscoveryProvider.OFFICIAL_WEB,
            ),
        )

        plan = SourceDiscoveryPlanner(
            policy=policy
        ).build(
            make_question(
                KnowledgeGapType.CONTRADICTION
            )
        )

        self.assertEqual(len(plan.queries), 1)
        self.assertEqual(
            plan.queries[0].provider,
            DiscoveryProvider.OFFICIAL_WEB,
        )

    def test_budget_limits_query_count(self) -> None:
        budget = DiscoveryBudget(
            max_queries=1,
            max_results_per_query=5,
            max_total_results=5,
        )

        plan = SourceDiscoveryPlanner(
            budget=budget
        ).build(
            make_question(
                KnowledgeGapType.CONTRADICTION
            )
        )

        self.assertEqual(len(plan.queries), 1)

    def test_invalid_budget_is_blocked(self) -> None:
        with self.assertRaises(ValueError):
            DiscoveryBudget(
                max_queries=1,
                max_results_per_query=2,
                max_total_results=3,
            )

    def test_auto_ingest_cannot_be_enabled(self) -> None:
        with self.assertRaises(ValueError):
            DiscoveryPolicy(
                allowed_source_types=(
                    SourceType.ACADEMIC_PAPER,
                ),
                allowed_providers=(
                    DiscoveryProvider.ACADEMIC_SEARCH,
                ),
                auto_ingest=True,
            )

    def test_auto_validate_cannot_be_enabled(self) -> None:
        with self.assertRaises(ValueError):
            DiscoveryPolicy(
                allowed_source_types=(
                    SourceType.ACADEMIC_PAPER,
                ),
                allowed_providers=(
                    DiscoveryProvider.ACADEMIC_SEARCH,
                ),
                auto_validate=True,
            )

    def test_default_plan_uses_research_grade_sources(self) -> None:
        plan = SourceDiscoveryPlanner().build(
            make_question(
                KnowledgeGapType.INSUFFICIENT_INDEPENDENCE
            )
        )

        self.assertTrue(
            all(
                SourceType.COMMUNITY
                not in query.source_types
                and SourceType.NEWS
                not in query.source_types
                for query in plan.queries
            )
        )

    def test_missing_directional_evidence_has_discovery_plan(self) -> None:
        plan = SourceDiscoveryPlanner().build(
            make_question(
                KnowledgeGapType.MISSING_DIRECTIONAL_EVIDENCE
            )
        )

        self.assertGreaterEqual(len(plan.queries), 1)

    def test_plan_never_validates_or_authorizes_execution(self) -> None:
        plan = SourceDiscoveryPlanner().build(
            make_question(
                KnowledgeGapType.CONTRADICTION
            )
        )

        self.assertFalse(plan.knowledge_validated)
        self.assertFalse(plan.production_approved)
        self.assertFalse(plan.execution_authorized)
        self.assertFalse(plan.policy.auto_ingest)
        self.assertFalse(plan.policy.auto_validate)

    def test_release_check(self) -> None:
        self.assertEqual(
            discovery_release_check()["safety"],
            "pass",
        )


if __name__ == "__main__":
    unittest.main()
