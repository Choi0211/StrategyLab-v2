from __future__ import annotations

import unittest
import tempfile

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

    def test_release_check_passes(self) -> None:
        payload = autonomous_external_research_execution_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertGreaterEqual(payload["claims"], 1)


if __name__ == "__main__":
    unittest.main()
