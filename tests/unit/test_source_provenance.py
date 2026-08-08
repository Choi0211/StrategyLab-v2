from __future__ import annotations

import hashlib
import unittest

from gaon.knowledge.provenance import (
    SourceProvenance,
    SourceType,
    TrustLevel,
    canonical_source_id,
    provenance_release_check,
)


class SourceProvenanceTests(unittest.TestCase):
    def test_source_id_is_deterministic(self) -> None:
        digest = hashlib.sha256(b"paper").hexdigest()
        first = canonical_source_id(
            source_type=SourceType.ACADEMIC_PAPER,
            locator="https://example.invalid/paper",
            content_sha256=digest,
        )
        second = canonical_source_id(
            source_type=SourceType.ACADEMIC_PAPER,
            locator="https://example.invalid/paper",
            content_sha256=digest,
        )
        self.assertEqual(first, second)

    def test_source_requires_valid_sha256(self) -> None:
        with self.assertRaises(ValueError):
            SourceProvenance.create(
                source_type=SourceType.WEB_ARTICLE,
                title="Example",
                locator="https://example.invalid",
                content_sha256="bad",
            )

    def test_external_content_never_defaults_to_validated(self) -> None:
        digest = hashlib.sha256(b"external").hexdigest()
        source = SourceProvenance.create(
            source_type=SourceType.WEB_ARTICLE,
            title="External",
            locator="https://example.invalid",
            content_sha256=digest,
            trust_level=TrustLevel.LOW,
        )
        self.assertFalse(source.validated_knowledge)
        self.assertFalse(source.production_approved)
        self.assertEqual(
            source.external_content_policy,
            "evidence-not-instruction",
        )

    def test_release_check(self) -> None:
        self.assertEqual(provenance_release_check()["safety"], "pass")


if __name__ == "__main__":
    unittest.main()
