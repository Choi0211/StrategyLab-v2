import unittest

from gaon.knowledge.content_acquisition import (
    ContentAcquisitionRecord,
    ContentAcquisitionStatus,
)
from gaon.knowledge.content_normalization import (
    ContentNormalizationStatus,
    NormalizationFailureKind,
    SafeContentNormalizer,
    content_normalization_release_check,
)


def acquisition(content_type: str, *, acquired: bool = True) -> ContentAcquisitionRecord:
    return ContentAcquisitionRecord(
        acquisition_id="content-acquisition:" + "a" * 64,
        discovery_result_id="discovery-result:test",
        source_locator="https://example.invalid/source",
        content_url="https://example.invalid/source",
        final_url="https://example.invalid/source",
        content_type=content_type,
        byte_count=10,
        content_sha256="0" * 64,
        status=ContentAcquisitionStatus.ACQUIRED if acquired else ContentAcquisitionStatus.BLOCKED,
        failure_kind=None,
        error_message=None,
        source_id="source:" + "b" * 64,
        raw_path=None,
        metadata_path=None,
        actual_source_body_fetched=acquired,
        stored_as_inert_evidence=acquired,
    )


class SafeContentNormalizerTests(unittest.TestCase):
    def test_text_plain_utf8_safe_normalized_text(self) -> None:
        record = SafeContentNormalizer().normalize(acquisition("text/plain"), "가온 evidence\ntext".encode("utf-8"))

        self.assertEqual(record.status, ContentNormalizationStatus.NORMALIZED)
        self.assertEqual(record.normalized_text, "가온 evidence text")
        self.assertTrue(record.eligible_for_claim_extraction)
        self.assertFalse(record.knowledge_validated)
        self.assertFalse(record.production_approved)

    def test_html_removes_script_style_and_navigation_noise(self) -> None:
        record = SafeContentNormalizer().normalize(
            acquisition("text/html"),
            b"<html><nav>menu</nav><style>body{}</style><script>alert(1)</script><main>Breakout evidence.</main></html>",
        )

        self.assertEqual(record.status, ContentNormalizationStatus.NORMALIZED)
        self.assertIn("Breakout evidence.", record.normalized_text)
        self.assertNotIn("alert", record.normalized_text)
        self.assertNotIn("menu", record.normalized_text)
        self.assertFalse(record.content_instructions_executed)

    def test_json_parses_data_only_and_extracts_bounded_text_values(self) -> None:
        record = SafeContentNormalizer().normalize(
            acquisition("application/json"),
            b'{"title":"Fixture", "items":[{"abstract":"Momentum needs independent evidence."}]}',
        )

        self.assertEqual(record.status, ContentNormalizationStatus.NORMALIZED)
        self.assertIn("Fixture", record.normalized_text)
        self.assertIn("Momentum needs independent evidence.", record.normalized_text)

    def test_invalid_json_fails_closed(self) -> None:
        record = SafeContentNormalizer().normalize(acquisition("application/json"), b'{"broken":')

        self.assertEqual(record.status, ContentNormalizationStatus.FAILED)
        self.assertEqual(record.failure_kind, NormalizationFailureKind.INVALID_JSON)
        self.assertFalse(record.eligible_for_claim_extraction)

    def test_pdf_without_safe_extractor_is_unsupported(self) -> None:
        record = SafeContentNormalizer().normalize(acquisition("application/pdf"), b"%PDF-1.4")

        self.assertEqual(record.status, ContentNormalizationStatus.UNSUPPORTED)
        self.assertEqual(record.failure_kind, NormalizationFailureKind.PDF_TEXT_UNAVAILABLE)
        self.assertFalse(record.eligible_for_claim_extraction)

    def test_blocked_acquisition_cannot_be_normalized_for_claims(self) -> None:
        record = SafeContentNormalizer().normalize(acquisition("text/plain", acquired=False), b"text")

        self.assertEqual(record.status, ContentNormalizationStatus.FAILED)
        self.assertEqual(record.failure_kind, NormalizationFailureKind.ACQUISITION_NOT_ELIGIBLE)
        self.assertFalse(record.eligible_for_claim_extraction)

    def test_release_check_passes(self) -> None:
        payload = content_normalization_release_check()

        self.assertEqual(payload["safety"], "pass")


if __name__ == "__main__":
    unittest.main()
