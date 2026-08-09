from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace

from gaon.knowledge.content_acquisition import (
    ContentAcquisitionRecord,
    ContentAcquisitionStatus,
)
from gaon.knowledge.content_claim_bridge import (
    ContentClaimBridgeBlocker,
    ContentClaimBridgeStatus,
    NormalizedContentClaimBridge,
    content_claim_bridge_release_check,
)
from gaon.knowledge.content_normalization import (
    ContentNormalizationStatus,
    SafeContentNormalizer,
)
from gaon.knowledge.provenance import (
    SourceProvenance,
    SourceType,
    TrustLevel,
)


def _source_and_normalized(
    text: str = (
        "Trend following should be tested across different regimes. "
        "Transaction costs can reduce realized returns."
    ),
) -> tuple[SourceProvenance, object]:
    raw = text.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    source = SourceProvenance.create(
        source_type=SourceType.ACADEMIC_PAPER,
        title="Bridge Test Source",
        locator="https://example.invalid/bridge-test",
        content_sha256=digest,
        trust_level=TrustLevel.HIGH,
        author="Researcher",
        publisher="Journal",
        published_at="2026-01-01",
        license_name="test-only",
        ingested_at="2026-08-08T00:00:00+00:00",
    )
    acquisition = ContentAcquisitionRecord(
        acquisition_id="content-acquisition:bridge-test",
        discovery_result_id="discovery-result:bridge-test",
        source_locator=source.locator,
        content_url=source.locator,
        final_url=source.locator,
        content_type="text/plain",
        byte_count=len(raw),
        content_sha256=digest,
        status=ContentAcquisitionStatus.ACQUIRED,
        failure_kind=None,
        error_message=None,
        source_id=source.source_id,
        raw_path=None,
        metadata_path=None,
        actual_source_body_fetched=True,
        stored_as_inert_evidence=True,
    )
    return source, SafeContentNormalizer().normalize(acquisition, raw)


class NormalizedContentClaimBridgeTests(unittest.TestCase):
    def test_normalized_text_becomes_verbatim_claim_candidates(self) -> None:
        source, normalized = _source_and_normalized()

        result = NormalizedContentClaimBridge().extract(normalized, source)

        self.assertEqual(ContentClaimBridgeStatus.EXTRACTED, result.status)
        self.assertEqual(2, len(result.claims))
        self.assertEqual(2, len(result.candidates))
        for claim in result.claims:
            self.assertIn(claim.text, normalized.normalized_text)
            self.assertEqual(source.source_id, claim.source_id)
        self.assertFalse(result.knowledge_validated)
        self.assertFalse(result.production_approved)
        self.assertFalse(result.strategy_mutated)
        self.assertFalse(result.order_executed)

    def test_unsupported_normalized_content_is_blocked(self) -> None:
        source, normalized = _source_and_normalized()
        normalized = replace(
            normalized,
            status=ContentNormalizationStatus.UNSUPPORTED,
            eligible_for_claim_extraction=False,
        )

        result = NormalizedContentClaimBridge().extract(normalized, source)

        self.assertEqual(ContentClaimBridgeStatus.BLOCKED, result.status)
        self.assertIn(
            ContentClaimBridgeBlocker.NORMALIZATION_NOT_ELIGIBLE,
            result.blockers,
        )
        self.assertEqual((), result.claims)
        self.assertEqual((), result.candidates)

    def test_source_checksum_mismatch_is_blocked(self) -> None:
        source, normalized = _source_and_normalized()
        other = SourceProvenance.create(
            source_type=SourceType.ACADEMIC_PAPER,
            title="Other Source",
            locator=source.locator,
            content_sha256="0" * 64,
            trust_level=TrustLevel.HIGH,
            ingested_at="2026-08-08T00:00:00+00:00",
        )

        result = NormalizedContentClaimBridge().extract(normalized, other)

        self.assertEqual(ContentClaimBridgeStatus.BLOCKED, result.status)
        self.assertIn(
            ContentClaimBridgeBlocker.CHECKSUM_MISMATCH,
            result.blockers,
        )

    def test_rejected_quality_is_blocked(self) -> None:
        source, normalized = _source_and_normalized()
        rejected_source = SourceProvenance.create(
            source_type=SourceType.UNKNOWN,
            title=source.title,
            locator=source.locator,
            content_sha256=source.content_sha256,
            trust_level=TrustLevel.UNKNOWN,
            ingested_at="2026-08-08T00:00:00+00:00",
        )

        result = NormalizedContentClaimBridge().extract(
            normalized,
            rejected_source,
        )

        self.assertEqual(ContentClaimBridgeStatus.BLOCKED, result.status)
        self.assertIn(
            ContentClaimBridgeBlocker.QUALITY_REJECTED,
            result.blockers,
        )

    def test_release_check_passes(self) -> None:
        payload = content_claim_bridge_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual(2, payload["claims"])
        self.assertEqual(2, payload["candidates"])


if __name__ == "__main__":
    unittest.main()
