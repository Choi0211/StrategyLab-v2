from __future__ import annotations

import unittest
import tempfile
from typing import Mapping

from gaon.knowledge.content_acquisition import (
    BoundedSourceContentAcquirer,
    ContentAcquisitionPolicy,
    FetchPayload,
)
from gaon.knowledge.discovery_ingestion import DiscoveryEvidenceIngestor
from gaon.knowledge.discovery import DiscoveryProvider, DiscoveryResult, DiscoveryStatus
from gaon.knowledge.execution import DiscoveryExecutionRun, QueryExecutionRecord
from gaon.knowledge.external_research_execution import (
    AutonomousExternalResearchExecutor,
    ContentResolutionRecord,
    ContentResolutionStatus,
    ExternalResearchExecutionPolicy,
    ExternalResearchTerminalState,
    autonomous_external_research_execution_release_check,
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
from gaon.knowledge.conflicts import ConflictStatus
from gaon.storage.foundation import GaonStorage


def _question() -> ResearchQuestion:
    return ResearchQuestion(
        question_id="research-question:test-external-execution",
        topic_key="strategy.breakout.robustness",
        gap_type=KnowledgeGapType.INSUFFICIENT_INDEPENDENCE,
        question="What evidence supports breakout robustness?",
        priority=ResearchPriority.HIGH,
        required_evidence=(
            RequiredEvidence(
                RequiredEvidenceType.INDEPENDENT_PRIMARY_SOURCE,
                1,
                "test",
            ),
        ),
        stop_conditions=(ResearchStopCondition.TWO_INDEPENDENT_PRIMARY_SOURCES,),
        parent_conflict_id="knowledge-conflict:test-external-execution",
        source_state=ConflictStatus.INSUFFICIENT_INDEPENDENCE,
    )


class FixtureDiscoveryExecutor:
    def __init__(self, *, locator: str = "https://example.org/research.html") -> None:
        self.locator = locator

    def execute(self, plan):  # type: ignore[no-untyped-def]
        result = DiscoveryResult(
            result_id="discovery-result:test",
            query_id=plan.queries[0].query_id,
            provider=DiscoveryProvider.ACADEMIC_SEARCH,
            title="Financial market breakout trading rule fixture research",
            locator=self.locator,
            source_type=SourceType.RESEARCH_REPORT,
            status=DiscoveryStatus.DISCOVERED,
            abstract=(
                "Fixture evidence about equity market trend following, "
                "breakout rules, and out-of-sample robustness."
            ),
        )
        return DiscoveryExecutionRun(
            run_id="source-discovery-run:test",
            plan_id=plan.plan_id,
            network_enabled=False,
            network_executed=False,
            provider_calls=1,
            results=(result,),
            query_records=(
                QueryExecutionRecord(
                    plan.queries[0].query_id,
                    DiscoveryProvider.ACADEMIC_SEARCH,
                    DiscoveryStatus.DISCOVERED,
                    1,
                    1,
                    1,
                ),
            ),
            duplicate_results=0,
            budget_exhausted=False,
        )


class FixtureTransport:
    def fetch(self, target, *, policy):  # type: ignore[no-untyped-def]
        return FetchPayload(
            final_url=target.content_url,
            content_type="text/html",
            content=(
                b"<html><body>Claim: breakout filters can reduce false signals."
                b" Claim: independent validation should be required.</body></html>"
            ),
        )


class MultiResultDiscoveryExecutor:
    def __init__(self, results: tuple[DiscoveryResult, ...]) -> None:
        self.results = results

    def execute(self, plan):  # type: ignore[no-untyped-def]
        return DiscoveryExecutionRun(
            run_id="source-discovery-run:multi",
            plan_id=plan.plan_id,
            network_enabled=False,
            network_executed=False,
            provider_calls=1,
            results=self.results,
            query_records=(
                QueryExecutionRecord(
                    plan.queries[0].query_id,
                    DiscoveryProvider.ACADEMIC_SEARCH,
                    DiscoveryStatus.DISCOVERED,
                    1,
                    len(self.results),
                    len(self.results),
                ),
            ),
            duplicate_results=0,
            budget_exhausted=False,
        )


class SequencedResolver:
    def __init__(self, statuses: Mapping[str, ContentResolutionStatus]) -> None:
        self.statuses = statuses
        self.calls: list[str] = []

    def resolve(self, result):  # type: ignore[no-untyped-def]
        result_id = str(result.result_id)
        self.calls.append(result_id)
        status = self.statuses.get(result_id, ContentResolutionStatus.DIRECT_CONTENT_URL)
        if status is ContentResolutionStatus.RESOLUTION_FAILURE:
            return ContentResolutionRecord(
                discovery_result_id=result_id,
                provider=result.provider.value,
                title=result.title,
                original_locator=result.locator,
                locator_kind="doi_url",
                doi=result.doi,
                resolution_attempted=True,
                status=ContentResolutionStatus.RESOLUTION_FAILURE,
                failure_kind="resolution_failure",
                error_message="HTTP Error 403: Forbidden",
            )
        return ContentResolutionRecord(
            discovery_result_id=result_id,
            provider=result.provider.value,
            title=result.title,
            original_locator=result.locator,
            locator_kind="doi_url",
            doi=result.doi,
            resolution_attempted=True,
            status=ContentResolutionStatus.DOI_RESOLVED,
            resolved_content_url=f"https://example.org/{result_id}.html",
            final_url=f"https://example.org/{result_id}.html",
            final_host="example.org",
        )


def _multi_result(result_id: str, doi: str, *, score_terms: str = "") -> DiscoveryResult:
    return DiscoveryResult(
        result_id=result_id,
        query_id="discovery-query:multi",
        provider=DiscoveryProvider.ACADEMIC_SEARCH,
        title=f"Financial market breakout trading rules {score_terms}",
        locator=f"https://doi.org/{doi}",
        source_type=SourceType.RESEARCH_REPORT,
        status=DiscoveryStatus.DISCOVERED,
        doi=doi,
        abstract=(
            "Equity market trend following breakout moving average trading rules "
            "volume confirmation out-of-sample robustness."
        ),
    )


def _executor(locator: str = "https://example.org/research.html") -> AutonomousExternalResearchExecutor:
    storage = GaonStorage(tempfile.mkdtemp(prefix="gaon-external-research-test-"))
    return AutonomousExternalResearchExecutor(
        discovery_executor=FixtureDiscoveryExecutor(locator=locator),  # type: ignore[arg-type]
        ingestion=DiscoveryEvidenceIngestor(storage),
        acquirer=BoundedSourceContentAcquirer(
            storage,
            policy=ContentAcquisitionPolicy(
                network_enabled=True,
                allowed_hosts=("example.org",),
                max_content_bytes=8_000,
            ),
            transport=FixtureTransport(),  # type: ignore[arg-type]
        ),
        policy=ExternalResearchExecutionPolicy(
            max_provider_calls=1,
            max_sources=1,
            max_total_download_bytes=8_000,
            content_network_enabled=True,
            allowed_content_hosts=("example.org",),
        ),
    )


class AutonomousExternalResearchExecutionTests(unittest.TestCase):
    def test_end_to_end_fixture_orchestrates_existing_components(self) -> None:
        result = _executor().run(_question())

        self.assertIn(
            result.state,
            {
                ExternalResearchTerminalState.EVIDENCE_SUFFICIENT,
                ExternalResearchTerminalState.UNRESOLVED_CONFLICT,
            },
        )
        self.assertEqual(1, result.provider_calls)
        self.assertEqual(1, result.acquired_sources)
        self.assertEqual(1, len(result.normalized_records))
        self.assertGreaterEqual(len(result.candidates), 1)
        self.assertIsNotNone(result.reevaluation)
        self.assertFalse(result.strategy_mutated)
        self.assertFalse(result.order_executed)

    def test_metadata_only_locator_returns_content_unavailable(self) -> None:
        result = _executor(locator="doi:10.1234/fixture").run(_question())

        self.assertEqual(ExternalResearchTerminalState.CONTENT_UNAVAILABLE, result.state)
        self.assertEqual(0, result.acquired_sources)
        self.assertIn("content_unavailable", " ".join(result.blockers))

    def test_hotfix1923_first_resolution_failure_falls_back_to_second_source(self) -> None:
        storage = GaonStorage(tempfile.mkdtemp(prefix="gaon-hotfix1923-fallback-"))
        resolver = SequencedResolver({"discovery-result:first": ContentResolutionStatus.RESOLUTION_FAILURE})
        executor = AutonomousExternalResearchExecutor(
            discovery_executor=MultiResultDiscoveryExecutor(
                (
                    _multi_result("discovery-result:first", "10.1142/9789813225107_0009", score_terms="robustness volume"),
                    _multi_result("discovery-result:second", "10.1007/978-3-031-90907-8_3"),
                    _multi_result("discovery-result:third", "10.1007/978-3-031-90907-8_14"),
                )
            ),  # type: ignore[arg-type]
            ingestion=DiscoveryEvidenceIngestor(storage),
            acquirer=BoundedSourceContentAcquirer(
                storage,
                policy=ContentAcquisitionPolicy(network_enabled=True, allowed_hosts=("example.org",), max_content_bytes=8_000),
                transport=FixtureTransport(),  # type: ignore[arg-type]
            ),
            resolver=resolver,  # type: ignore[arg-type]
            policy=ExternalResearchExecutionPolicy(
                max_provider_calls=1,
                max_sources=2,
                max_relevant_candidates=3,
                max_resolution_attempts=3,
                max_content_acquisition_attempts=3,
                max_acquired_sources=2,
                max_grounded_sources=2,
                max_total_download_bytes=8_000,
                content_network_enabled=True,
                allowed_content_hosts=("example.org",),
            ),
        )

        result = executor.run(_question())

        self.assertIn(result.state, {ExternalResearchTerminalState.EVIDENCE_SUFFICIENT, ExternalResearchTerminalState.UNRESOLVED_CONFLICT})
        self.assertEqual(["discovery-result:first", "discovery-result:second"], resolver.calls)
        self.assertEqual(2, len(result.resolution_records))
        self.assertEqual("resolution_failure", result.resolution_records[0].failure_kind)
        self.assertEqual(1, result.acquired_sources)
        self.assertGreaterEqual(len(result.candidates), 1)

    def test_hotfix1923_resolution_budget_and_duplicate_doi_are_bounded(self) -> None:
        storage = GaonStorage(tempfile.mkdtemp(prefix="gaon-hotfix1923-budget-"))
        resolver = SequencedResolver(
            {
                "discovery-result:first": ContentResolutionStatus.RESOLUTION_FAILURE,
                "discovery-result:second": ContentResolutionStatus.RESOLUTION_FAILURE,
            }
        )
        executor = AutonomousExternalResearchExecutor(
            discovery_executor=MultiResultDiscoveryExecutor(
                (
                    _multi_result("discovery-result:first", "10.1234/duplicate"),
                    _multi_result("discovery-result:duplicate", "10.1234/duplicate"),
                    _multi_result("discovery-result:second", "10.1234/second"),
                    _multi_result("discovery-result:third", "10.1234/third"),
                )
            ),  # type: ignore[arg-type]
            ingestion=DiscoveryEvidenceIngestor(storage),
            acquirer=BoundedSourceContentAcquirer(
                storage,
                policy=ContentAcquisitionPolicy(network_enabled=True, allowed_hosts=("example.org",), max_content_bytes=8_000),
                transport=FixtureTransport(),  # type: ignore[arg-type]
            ),
            resolver=resolver,  # type: ignore[arg-type]
            policy=ExternalResearchExecutionPolicy(
                max_provider_calls=1,
                max_sources=2,
                max_relevant_candidates=4,
                max_resolution_attempts=2,
                max_content_acquisition_attempts=2,
                max_acquired_sources=2,
                max_grounded_sources=2,
                max_total_download_bytes=8_000,
                content_network_enabled=True,
                allowed_content_hosts=("example.org",),
            ),
        )

        result = executor.run(_question())

        self.assertEqual(["discovery-result:first", "discovery-result:second"], resolver.calls)
        self.assertEqual(2, len(result.resolution_records))
        self.assertIn("duplicate_source_candidate:discovery-result:duplicate", result.blockers)
        self.assertIn("resolution_budget_exhausted:discovery-result:third", result.blockers)
        self.assertEqual(ExternalResearchTerminalState.CONTENT_UNAVAILABLE, result.state)

    def test_hotfix1923_all_relevant_sources_exhausted_is_precise(self) -> None:
        storage = GaonStorage(tempfile.mkdtemp(prefix="gaon-hotfix1923-exhausted-"))
        resolver = SequencedResolver(
            {
                "discovery-result:first": ContentResolutionStatus.RESOLUTION_FAILURE,
                "discovery-result:second": ContentResolutionStatus.RESOLUTION_FAILURE,
            }
        )
        executor = AutonomousExternalResearchExecutor(
            discovery_executor=MultiResultDiscoveryExecutor(
                (
                    _multi_result("discovery-result:first", "10.1234/first"),
                    _multi_result("discovery-result:second", "10.1234/second"),
                )
            ),  # type: ignore[arg-type]
            ingestion=DiscoveryEvidenceIngestor(storage),
            acquirer=BoundedSourceContentAcquirer(
                storage,
                policy=ContentAcquisitionPolicy(network_enabled=True, allowed_hosts=("example.org",), max_content_bytes=8_000),
                transport=FixtureTransport(),  # type: ignore[arg-type]
            ),
            resolver=resolver,  # type: ignore[arg-type]
            policy=ExternalResearchExecutionPolicy(
                max_provider_calls=1,
                max_sources=2,
                max_relevant_candidates=2,
                max_resolution_attempts=2,
                max_content_acquisition_attempts=2,
                max_acquired_sources=2,
                max_grounded_sources=2,
                max_total_download_bytes=8_000,
                content_network_enabled=True,
                allowed_content_hosts=("example.org",),
            ),
        )

        result = executor.run(_question())

        self.assertEqual(ExternalResearchTerminalState.ACADEMIC_CONTENT_EXHAUSTED, result.state)
        self.assertEqual(0, result.acquired_sources)
        self.assertEqual(2, len(result.resolution_records))

    def test_release_check_passes(self) -> None:
        payload = autonomous_external_research_execution_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertGreaterEqual(payload["claims"], 1)


if __name__ == "__main__":
    unittest.main()
