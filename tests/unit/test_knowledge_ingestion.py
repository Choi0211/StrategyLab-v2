from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gaon.knowledge.ingestion import (
    KnowledgeIngestor,
    ingestion_release_check,
)
from gaon.knowledge.provenance import SourceType, TrustLevel
from gaon.storage.foundation import GaonStorage


class KnowledgeIngestionTests(unittest.TestCase):
    def test_ingest_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = GaonStorage(Path(tmp) / "Gaon")
            ingestor = KnowledgeIngestor(storage)

            kwargs = dict(
                source_type=SourceType.ACADEMIC_PAPER,
                title="Paper",
                locator="https://example.invalid/paper",
                trust_level=TrustLevel.MODERATE,
                suffix=".pdf",
            )

            first = ingestor.ingest_bytes(b"paper bytes", **kwargs)
            second = ingestor.ingest_bytes(b"paper bytes", **kwargs)

            self.assertEqual(first.status, "stored")
            self.assertEqual(second.status, "duplicate_skipped")
            self.assertEqual(
                first.source.source_id,
                second.source.source_id,
            )

    def test_size_budget_blocks_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ingestor = KnowledgeIngestor(
                GaonStorage(Path(tmp) / "Gaon"),
                max_source_bytes=4,
            )
            with self.assertRaises(ValueError):
                ingestor.ingest_bytes(
                    b"12345",
                    source_type=SourceType.USER_PROVIDED,
                    title="Too Large",
                    locator="user://too-large",
                )

    def test_unsafe_suffix_is_neutralized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ingestor = KnowledgeIngestor(
                GaonStorage(Path(tmp) / "Gaon")
            )
            result = ingestor.ingest_bytes(
                b"echo unsafe",
                source_type=SourceType.USER_PROVIDED,
                title="Untrusted",
                locator="user://untrusted",
                suffix=".sh;rm",
            )
            self.assertTrue(result.raw_path.endswith(".bin"))

    def test_metadata_is_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ingestor = KnowledgeIngestor(
                GaonStorage(Path(tmp) / "Gaon")
            )
            result = ingestor.ingest_bytes(
                b"external text",
                source_type=SourceType.WEB_ARTICLE,
                title="External Article",
                locator="https://example.invalid/article",
            )
            metadata = ingestor.read_metadata(result.source.source_id)

            self.assertEqual(
                metadata["content_policy"],
                "untrusted-evidence-only",
            )
            self.assertFalse(metadata["executable"])
            self.assertFalse(metadata["knowledge_validated"])
            self.assertFalse(metadata["production_approved"])

    def test_release_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = ingestion_release_check(Path(tmp) / "Gaon")
            self.assertEqual(payload["safety"], "pass")


if __name__ == "__main__":
    unittest.main()
