from __future__ import annotations

import unittest
from urllib.parse import urlparse

from gaon.knowledge.conflicts import (
    ConflictStatus,
)
from gaon.knowledge.discovery import (
    DiscoveryBudget,
    DiscoveryPolicy,
    DiscoveryProvider,
    DiscoveryQuery,
    DiscoveryStatus,
    SourceDiscoveryPlan,
    SourceDiscoveryPlanner,
    canonical_plan_id,
    canonical_query_id,
)
from gaon.knowledge.execution import (
    BoundedSourceDiscoveryExecutor,
    CrossrefDiscoveryProvider,
    DataCiteDiscoveryProvider,
    ExecutionFailureKind,
    FixtureTransport,
    NetworkExecutionPolicy,
    canonical_result_id,
    execution_release_check,
)
from gaon.knowledge.gaps import (
    KnowledgeGapType,
    RequiredEvidence,
    RequiredEvidenceType,
    ResearchPriority,
    ResearchQuestion,
    ResearchStopCondition,
)
from gaon.knowledge.provenance import (
    SourceType,
)


def question() -> ResearchQuestion:
    return ResearchQuestion(
        question_id="research-question:test",
        topic_key="trend.regime.robustness",
        gap_type=KnowledgeGapType.CONTRADICTION,
        question="Test question",
        priority=ResearchPriority.HIGH,
        required_evidence=(
            RequiredEvidence(
                evidence_type=(
                    RequiredEvidenceType
                    .INDEPENDENT_PRIMARY_SOURCE
                ),
                minimum_independent_sources=2,
                rationale="test",
            ),
        ),
        stop_conditions=(
            ResearchStopCondition
            .OPPOSING_EVIDENCE_RESOLVED,
        ),
        parent_conflict_id=(
            "knowledge-conflict:test"
        ),
        source_state=(
            ConflictStatus.UNRESOLVED_CONFLICT
        ),
    )


class DuplicateTransport:
    def get_json(
        self,
        url: str,
        *,
        policy: NetworkExecutionPolicy,
    ):
        host = urlparse(url).hostname

        if host == "api.crossref.org":
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/same",
                            "title": [
                                "Duplicate Research"
                            ],
                            "type": (
                                "journal-article"
                            ),
                        }
                    ]
                }
            }

        if host == "api.datacite.org":
            return {
                "data": []
            }

        raise PermissionError("blocked")


class InvalidTransport:
    def get_json(
        self,
        url: str,
        *,
        policy: NetworkExecutionPolicy,
    ):
        return {"unexpected": True}


class SourceDiscoveryExecutionTests(
    unittest.TestCase
):
    def test_result_id_is_deterministic(self) -> None:
        first = canonical_result_id(
            query_id="discovery-query:test",
            locator=(
                "https://doi.org/10.1000/test"
            ),
        )

        second = canonical_result_id(
            query_id="discovery-query:test",
            locator=(
                "https://doi.org/10.1000/test"
            ),
        )

        self.assertEqual(first, second)

    def test_network_disabled_fails_closed(
        self,
    ) -> None:
        plan = SourceDiscoveryPlanner().build(
            question()
        )

        result = (
            BoundedSourceDiscoveryExecutor(
                network_policy=(
                    NetworkExecutionPolicy(
                        network_enabled=False
                    )
                ),
                transport=FixtureTransport(),
            ).execute(plan)
        )

        self.assertFalse(
            result.network_executed
        )
        self.assertEqual(
            result.provider_calls,
            0,
        )

        self.assertTrue(
            all(
                record.failure_kind
                is ExecutionFailureKind.NETWORK_DISABLED
                for record in result.query_records
            )
        )

    def test_fixture_executes_real_provider_contracts(
        self,
    ) -> None:
        plan = SourceDiscoveryPlanner().build(
            question()
        )

        result = (
            BoundedSourceDiscoveryExecutor(
                network_policy=(
                    NetworkExecutionPolicy(
                        network_enabled=True
                    )
                ),
                transport=FixtureTransport(),
            ).execute(plan)
        )

        self.assertTrue(
            result.network_executed
        )

        self.assertGreaterEqual(
            len(result.results),
            3,
        )

    def test_crossref_parser_returns_paper(
        self,
    ) -> None:
        query = (
            SourceDiscoveryPlanner()
            .build(question())
            .queries[0]
        )

        results = (
            CrossrefDiscoveryProvider()
            .search(
                query_id=query.query_id,
                query=query.query,
                limit=5,
                requested_source_types=(
                    query.source_types
                ),
                transport=FixtureTransport(),
                policy=NetworkExecutionPolicy(
                    network_enabled=True
                ),
            )
        )

        self.assertEqual(
            results[0].source_type,
            SourceType.ACADEMIC_PAPER,
        )

    def test_datacite_parser_returns_dataset(
        self,
    ) -> None:
        plan = SourceDiscoveryPlanner().build(
            question()
        )

        query = next(
            item
            for item in plan.queries
            if item.provider
            is DiscoveryProvider.DATASET_CATALOG
        )

        results = (
            DataCiteDiscoveryProvider()
            .search(
                query_id=query.query_id,
                query=query.query,
                limit=5,
                requested_source_types=(
                    query.source_types
                ),
                transport=FixtureTransport(),
                policy=NetworkExecutionPolicy(
                    network_enabled=True
                ),
            )
        )

        self.assertEqual(
            results[0].source_type,
            SourceType.DATASET,
        )

    def test_results_remain_untrusted(
        self,
    ) -> None:
        plan = SourceDiscoveryPlanner().build(
            question()
        )

        result = (
            BoundedSourceDiscoveryExecutor(
                network_policy=(
                    NetworkExecutionPolicy(
                        network_enabled=True
                    )
                ),
                transport=FixtureTransport(),
            ).execute(plan)
        )

        for item in result.results:
            self.assertFalse(
                item.provenance_created
            )
            self.assertFalse(
                item.ingested
            )
            self.assertFalse(
                item.quality_evaluated
            )
            self.assertFalse(
                item.knowledge_validated
            )
            self.assertFalse(
                item.production_approved
            )

    def test_provider_call_budget_is_enforced(
        self,
    ) -> None:
        base = SourceDiscoveryPlanner().build(
            question()
        )

        budget = DiscoveryBudget(
            max_queries=1,
            max_results_per_query=2,
            max_total_results=2,
        )

        plan = SourceDiscoveryPlan(
            plan_id=base.plan_id,
            question_id=base.question_id,
            topic_key=base.topic_key,
            gap_type=base.gap_type,
            priority=base.priority,
            queries=base.queries,
            budget=budget,
            policy=base.policy,
        )

        result = (
            BoundedSourceDiscoveryExecutor(
                network_policy=(
                    NetworkExecutionPolicy(
                        network_enabled=True
                    )
                ),
                transport=FixtureTransport(),
            ).execute(plan)
        )

        self.assertLessEqual(
            result.provider_calls,
            1,
        )

        self.assertLessEqual(
            len(result.results),
            2,
        )

    def test_official_web_is_fail_closed(
        self,
    ) -> None:
        query_id = canonical_query_id(
            question_id=(
                "research-question:test"
            ),
            provider=(
                DiscoveryProvider.OFFICIAL_WEB
            ),
            query="official evidence",
        )

        query = DiscoveryQuery(
            query_id=query_id,
            question_id=(
                "research-question:test"
            ),
            provider=(
                DiscoveryProvider.OFFICIAL_WEB
            ),
            query="official evidence",
            source_types=(
                SourceType.OFFICIAL_DOCUMENT,
            ),
            sequence=0,
        )

        policy = DiscoveryPolicy(
            allowed_source_types=(
                SourceType.OFFICIAL_DOCUMENT,
            ),
            allowed_providers=(
                DiscoveryProvider.OFFICIAL_WEB,
            ),
        )

        budget = DiscoveryBudget(
            max_queries=1,
            max_results_per_query=2,
            max_total_results=2,
        )

        plan = SourceDiscoveryPlan(
            plan_id=canonical_plan_id(
                question_id=(
                    "research-question:test"
                ),
                query_ids=(query_id,),
            ),
            question_id=(
                "research-question:test"
            ),
            topic_key="test.topic",
            gap_type=(
                KnowledgeGapType
                .MISSING_DIRECTIONAL_EVIDENCE
            ),
            priority=ResearchPriority.MEDIUM,
            queries=(query,),
            budget=budget,
            policy=policy,
        )

        result = (
            BoundedSourceDiscoveryExecutor(
                network_policy=(
                    NetworkExecutionPolicy(
                        network_enabled=True
                    )
                ),
                transport=FixtureTransport(),
            ).execute(plan)
        )

        self.assertEqual(
            result.provider_calls,
            0,
        )

        self.assertEqual(
            result.query_records[0].status,
            DiscoveryStatus.BLOCKED,
        )

        self.assertEqual(
            result.query_records[0].failure_kind,
            ExecutionFailureKind.PROVIDER_UNSUPPORTED,
        )

    def test_invalid_provider_response_is_blocked(
        self,
    ) -> None:
        plan = SourceDiscoveryPlanner().build(
            question()
        )

        result = (
            BoundedSourceDiscoveryExecutor(
                network_policy=(
                    NetworkExecutionPolicy(
                        network_enabled=True
                    )
                ),
                transport=InvalidTransport(),
            ).execute(plan)
        )

        self.assertEqual(
            len(result.results),
            0,
        )

        self.assertTrue(
            any(
                record.failure_kind
                is ExecutionFailureKind.INVALID_RESPONSE
                for record in result.query_records
            )
        )

    def test_invalid_network_policy_is_blocked(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            NetworkExecutionPolicy(
                network_enabled=True,
                allowed_api_hosts=(
                    "https://bad.example",
                ),
            )

    def test_execution_never_mutates_or_orders(
        self,
    ) -> None:
        plan = SourceDiscoveryPlanner().build(
            question()
        )

        result = (
            BoundedSourceDiscoveryExecutor(
                network_policy=(
                    NetworkExecutionPolicy(
                        network_enabled=True
                    )
                ),
                transport=FixtureTransport(),
            ).execute(plan)
        )

        self.assertFalse(
            result.ingested
        )
        self.assertFalse(
            result.quality_evaluated
        )
        self.assertFalse(
            result.knowledge_validated
        )
        self.assertFalse(
            result.production_approved
        )
        self.assertFalse(
            result.strategy_mutated
        )
        self.assertFalse(
            result.order_executed
        )

    def test_release_check(self) -> None:
        self.assertEqual(
            execution_release_check()[
                "safety"
            ],
            "pass",
        )


if __name__ == "__main__":
    unittest.main()
