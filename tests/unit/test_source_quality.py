from __future__ import annotations

import hashlib
import unittest

from gaon.knowledge.provenance import (
    SourceProvenance,
    SourceType,
    TrustLevel,
)
from gaon.knowledge.quality import (
    EvidenceGate,
    EvidenceGateStatus,
    EvidenceUse,
    SourceQualityEvaluator,
    quality_release_check,
)


def make_source(
    *,
    source_type: SourceType,
    trust_level: TrustLevel,
    locator: str = "https://example.invalid/source",
    author: str | None = None,
    publisher: str | None = None,
    published_at: str | None = None,
    license_name: str | None = None,
) -> SourceProvenance:
    digest = hashlib.sha256(
        f"{source_type.value}:{trust_level.value}:{locator}".encode()
    ).hexdigest()

    return SourceProvenance.create(
        source_type=source_type,
        title=f"Test {source_type.value}",
        locator=locator,
        content_sha256=digest,
        trust_level=trust_level,
        author=author,
        publisher=publisher,
        published_at=published_at,
        license_name=license_name,
        ingested_at="2026-08-08T00:00:00+00:00",
    )


class SourceQualityTests(unittest.TestCase):
    def test_authoritative_official_document_is_primary(self) -> None:
        source = make_source(
            source_type=SourceType.OFFICIAL_DOCUMENT,
            trust_level=TrustLevel.AUTHORITATIVE,
            publisher="Official Publisher",
            published_at="2026-08-08",
            license_name="public",
        )

        result = SourceQualityEvaluator().evaluate(source)

        self.assertEqual(
            result.gate_status,
            EvidenceGateStatus.ACCEPTED,
        )
        self.assertEqual(
            result.evidence_use,
            EvidenceUse.PRIMARY,
        )
        self.assertFalse(result.knowledge_validated)
        self.assertFalse(result.production_approved)

    def test_academic_paper_with_metadata_is_primary(self) -> None:
        source = make_source(
            source_type=SourceType.ACADEMIC_PAPER,
            trust_level=TrustLevel.MODERATE,
            author="Researcher",
            publisher="Journal",
            published_at="2025-01-01",
            license_name="open",
        )

        result = SourceQualityEvaluator().evaluate(source)

        self.assertEqual(
            result.gate_status,
            EvidenceGateStatus.ACCEPTED,
        )

    def test_community_is_never_primary_on_provenance_alone(self) -> None:
        source = make_source(
            source_type=SourceType.COMMUNITY,
            trust_level=TrustLevel.HIGH,
            author="Known User",
        )

        result = SourceQualityEvaluator().evaluate(source)

        self.assertEqual(
            result.gate_status,
            EvidenceGateStatus.LIMITED,
        )
        self.assertEqual(
            result.evidence_use,
            EvidenceUse.DISCOVERY_ONLY,
        )

    def test_news_is_supporting_not_strategy_validation(self) -> None:
        source = make_source(
            source_type=SourceType.NEWS,
            trust_level=TrustLevel.HIGH,
            publisher="News Publisher",
            published_at="2026-08-08",
        )

        result = SourceQualityEvaluator().evaluate(source)

        self.assertEqual(
            result.gate_status,
            EvidenceGateStatus.LIMITED,
        )
        self.assertEqual(
            result.evidence_use,
            EvidenceUse.SUPPORTING,
        )

    def test_unknown_source_is_rejected(self) -> None:
        source = make_source(
            source_type=SourceType.UNKNOWN,
            trust_level=TrustLevel.UNKNOWN,
        )

        result = SourceQualityEvaluator().evaluate(source)

        self.assertEqual(
            result.gate_status,
            EvidenceGateStatus.REJECTED,
        )
        self.assertIn(
            "unknown_source_type",
            result.blockers,
        )

    def test_invalid_locator_is_rejected(self) -> None:
        source = make_source(
            source_type=SourceType.RESEARCH_REPORT,
            trust_level=TrustLevel.HIGH,
            locator="not-a-valid-locator",
        )

        result = SourceQualityEvaluator().evaluate(source)

        self.assertEqual(
            result.gate_status,
            EvidenceGateStatus.REJECTED,
        )
        self.assertIn(
            "invalid_locator",
            result.blockers,
        )

    def test_gate_partitions_sources(self) -> None:
        official = make_source(
            source_type=SourceType.OFFICIAL_DOCUMENT,
            trust_level=TrustLevel.AUTHORITATIVE,
            publisher="Official",
        )
        community = make_source(
            source_type=SourceType.COMMUNITY,
            trust_level=TrustLevel.LOW,
        )
        unknown = make_source(
            source_type=SourceType.UNKNOWN,
            trust_level=TrustLevel.UNKNOWN,
        )

        result = EvidenceGate().evaluate_many(
            (official, community, unknown)
        )

        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(len(result.limited), 1)
        self.assertEqual(len(result.rejected), 1)

    def test_release_check(self) -> None:
        payload = quality_release_check()
        self.assertEqual(payload["safety"], "pass")


if __name__ == "__main__":
    unittest.main()
