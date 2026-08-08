from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from gaon.knowledge.discovery import (
    DiscoveryProvider,
    DiscoveryResult,
    DiscoveryStatus,
)
from gaon.knowledge.discovery_ingestion import (
    ARTIFACT_SCOPE,
    DiscoveryEvidenceIngestor,
    canonical_discovery_snapshot,
    discovery_ingestion_release_check,
)
from gaon.knowledge.provenance import (
    SourceType,
)
from gaon.knowledge.quality import (
    EvidenceGateStatus,
    EvidenceUse,
)
from gaon.storage.foundation import (
    GaonStorage,
)


def paper_result() -> DiscoveryResult:
    return DiscoveryResult(
        result_id=(
            "discovery-result:test-paper"
        ),
        query_id=(
            "discovery-query:test-paper"
        ),
        provider=(
            DiscoveryProvider
            .ACADEMIC_SEARCH
        ),
        title=(
            "Trend Following Across "
            "Market Regimes"
        ),
        locator=(
            "https://doi.org/"
            "10.1000/test-paper"
        ),
        source_type=
            SourceType.ACADEMIC_PAPER,
        status=DiscoveryStatus.DISCOVERED,
    )


class DiscoveryIngestionTests(
    unittest.TestCase
):
    def test_snapshot_is_deterministic(
        self,
    ) -> None:
        result = paper_result()

        first = (
            canonical_discovery_snapshot(
                result
            )
        )

        second = (
            canonical_discovery_snapshot(
                result
            )
        )

        self.assertEqual(
            first,
            second,
        )

    def test_snapshot_explicitly_marks_metadata_only(
        self,
    ) -> None:
        payload = (
            canonical_discovery_snapshot(
                paper_result()
            ).decode("utf-8")
        )

        self.assertIn(
            '"artifact_scope":"discovery_metadata_only"',
            payload,
        )

        self.assertIn(
            '"actual_source_body_fetched":false',
            payload,
        )

        self.assertIn(
            '"eligible_for_claim_extraction":false',
            payload,
        )

    def test_discovered_result_creates_provenance_and_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge = (
                DiscoveryEvidenceIngestor(
                    GaonStorage(tmp)
                )
            )

            record = bridge.ingest_result(
                paper_result()
            )

            self.assertTrue(
                record.source_id.startswith(
                    "source:"
                )
            )

            self.assertTrue(
                Path(
                    record.raw_path
                ).is_file()
            )

            self.assertTrue(
                Path(
                    record.metadata_path
                ).is_file()
            )

    def test_metadata_quality_is_capped_at_limited(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge = (
                DiscoveryEvidenceIngestor(
                    GaonStorage(tmp)
                )
            )

            record = bridge.ingest_result(
                paper_result()
            )

            self.assertEqual(
                record.quality_status,
                EvidenceGateStatus.LIMITED,
            )

            self.assertEqual(
                record.evidence_use,
                EvidenceUse.SUPPORTING,
            )

    def test_source_body_and_claim_extraction_remain_blocked(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = (
                DiscoveryEvidenceIngestor(
                    GaonStorage(tmp)
                ).ingest_result(
                    paper_result()
                )
            )

            self.assertEqual(
                record.artifact_scope,
                ARTIFACT_SCOPE,
            )

            self.assertFalse(
                record
                .actual_source_body_fetched
            )

            self.assertFalse(
                record
                .eligible_for_claim_extraction
            )

            self.assertFalse(
                record.knowledge_validated
            )

    def test_non_discovered_result_is_rejected(
        self,
    ) -> None:
        result = replace(
            paper_result(),
            status=DiscoveryStatus.BLOCKED,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(
                ValueError
            ):
                DiscoveryEvidenceIngestor(
                    GaonStorage(tmp)
                ).ingest_result(
                    result
                )

    def test_prevalidated_result_is_rejected(
        self,
    ) -> None:
        result = replace(
            paper_result(),
            knowledge_validated=True,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(
                ValueError
            ):
                DiscoveryEvidenceIngestor(
                    GaonStorage(tmp)
                ).ingest_result(
                    result
                )

    def test_ingestion_is_idempotent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge = (
                DiscoveryEvidenceIngestor(
                    GaonStorage(tmp)
                )
            )

            first = bridge.ingest_result(
                paper_result()
            )

            second = bridge.ingest_result(
                paper_result()
            )

            self.assertFalse(
                first.duplicate
            )

            self.assertTrue(
                second.duplicate
            )

            self.assertEqual(
                first.source_id,
                second.source_id,
            )

    def test_duplicate_input_is_collapsed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = paper_result()

            run = (
                DiscoveryEvidenceIngestor(
                    GaonStorage(tmp)
                ).ingest_results(
                    (result, result),
                    discovery_run_id=(
                        "source-discovery-run:test"
                    ),
                )
            )

            self.assertEqual(
                len(run.records),
                1,
            )

            self.assertEqual(
                run.skipped_duplicates,
                1,
            )

    def test_run_never_validates_mutates_or_orders(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = (
                DiscoveryEvidenceIngestor(
                    GaonStorage(tmp)
                ).ingest_results(
                    (paper_result(),),
                    discovery_run_id=(
                        "source-discovery-run:test"
                    ),
                )
            )

            self.assertEqual(
                run.actual_source_bodies_fetched,
                0,
            )

            self.assertEqual(
                run.claim_extraction_runs,
                0,
            )

            self.assertFalse(
                run.knowledge_validated
            )

            self.assertFalse(
                run.production_approved
            )

            self.assertFalse(
                run.strategy_mutated
            )

            self.assertFalse(
                run.order_executed
            )

    def test_release_check(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = (
                discovery_ingestion_release_check(
                    tmp
                )
            )

            self.assertEqual(
                payload["safety"],
                "pass",
            )


if __name__ == "__main__":
    unittest.main()
