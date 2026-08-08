from __future__ import annotations

import hashlib
import unittest

from gaon.knowledge.claims import (
    KnowledgeCandidateBuilder,
    KnowledgeCandidateStatus,
    VerbatimClaimExtractor,
    canonical_claim_id,
    claims_release_check,
)
from gaon.knowledge.provenance import (
    SourceProvenance,
    SourceType,
    TrustLevel,
)
from gaon.knowledge.quality import (
    SourceQualityEvaluator,
)


def make_source(
    text: str,
    *,
    source_type: SourceType = SourceType.ACADEMIC_PAPER,
    trust_level: TrustLevel = TrustLevel.HIGH,
) -> SourceProvenance:
    return SourceProvenance.create(
        source_type=source_type,
        title="Test Source",
        locator="https://example.invalid/test-source",
        content_sha256=hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest(),
        trust_level=trust_level,
        author="Researcher",
        publisher="Publisher",
        published_at="2026-01-01",
        license_name="test",
        ingested_at="2026-08-08T00:00:00+00:00",
    )


class ClaimExtractionTests(unittest.TestCase):
    def test_claim_id_is_deterministic(self) -> None:
        text = "Market regimes can affect strategy performance."
        source = make_source(text)

        first = canonical_claim_id(
            source_id=source.source_id,
            text=text,
        )
        second = canonical_claim_id(
            source_id=source.source_id,
            text=text,
        )
        self.assertEqual(first, second)

    def test_extractor_returns_source_present_claims_only(self) -> None:
        text = (
            "Momentum can vary by market regime. "
            "Transaction costs can reduce returns."
        )
        source = make_source(text)

        claims = VerbatimClaimExtractor().extract(
            source,
            text,
        )

        self.assertEqual(len(claims), 2)
        self.assertTrue(
            all(claim.text in text for claim in claims)
        )
        self.assertTrue(
            all(claim.verbatim_from_source for claim in claims)
        )

    def test_duplicate_claims_are_removed(self) -> None:
        text = (
            "Costs matter in backtests. "
            "Costs matter in backtests."
        )
        source = make_source(text)

        claims = VerbatimClaimExtractor().extract(
            source,
            text,
        )

        self.assertEqual(len(claims), 1)

    def test_claims_are_never_validated_or_executable(self) -> None:
        text = "A backtest does not guarantee future returns."
        source = make_source(text)

        claim = VerbatimClaimExtractor().extract(
            source,
            text,
        )[0]

        self.assertFalse(claim.knowledge_validated)
        self.assertFalse(claim.production_approved)
        self.assertFalse(claim.executable)

    def test_accepted_source_builds_evidence_backed_candidate(self) -> None:
        text = "Market regime may affect trend-following performance."
        source = make_source(text)

        assessment = SourceQualityEvaluator().evaluate(source)
        claim = VerbatimClaimExtractor().extract(
            source,
            text,
        )[0]

        candidate = KnowledgeCandidateBuilder().build(
            claim,
            assessment,
        )

        self.assertEqual(
            candidate.status,
            KnowledgeCandidateStatus.EVIDENCE_BACKED,
        )
        self.assertFalse(candidate.knowledge_validated)
        self.assertFalse(candidate.research_tested)
        self.assertFalse(candidate.production_approved)
        self.assertFalse(candidate.policy_applied)

    def test_limited_source_builds_limited_candidate(self) -> None:
        text = "A news report describes a market event."
        source = make_source(
            text,
            source_type=SourceType.NEWS,
            trust_level=TrustLevel.HIGH,
        )

        assessment = SourceQualityEvaluator().evaluate(source)
        claim = VerbatimClaimExtractor().extract(
            source,
            text,
        )[0]

        candidate = KnowledgeCandidateBuilder().build(
            claim,
            assessment,
        )

        self.assertEqual(
            candidate.status,
            KnowledgeCandidateStatus.LIMITED_EVIDENCE,
        )

    def test_rejected_source_cannot_build_candidate(self) -> None:
        text = "Unknown material should not become knowledge."
        source = make_source(
            text,
            source_type=SourceType.UNKNOWN,
            trust_level=TrustLevel.UNKNOWN,
        )

        assessment = SourceQualityEvaluator().evaluate(source)
        claim = VerbatimClaimExtractor().extract(
            source,
            text,
        )[0]

        with self.assertRaises(ValueError):
            KnowledgeCandidateBuilder().build(
                claim,
                assessment,
            )

    def test_provenance_mismatch_is_blocked(self) -> None:
        first_text = "First research statement is sufficiently long."
        second_text = "Second research statement is sufficiently long."

        first = make_source(first_text)
        second = SourceProvenance.create(
            source_type=SourceType.OFFICIAL_DOCUMENT,
            title="Second Source",
            locator="https://example.invalid/second",
            content_sha256=hashlib.sha256(
                second_text.encode("utf-8")
            ).hexdigest(),
            trust_level=TrustLevel.AUTHORITATIVE,
            publisher="Official",
            ingested_at="2026-08-08T00:00:00+00:00",
        )

        claim = VerbatimClaimExtractor().extract(
            first,
            first_text,
        )[0]
        assessment = SourceQualityEvaluator().evaluate(
            second
        )

        with self.assertRaises(ValueError):
            KnowledgeCandidateBuilder().build(
                claim,
                assessment,
            )

    def test_max_claim_budget_is_enforced(self) -> None:
        text = (
            "Statement number one is long enough. "
            "Statement number two is long enough. "
            "Statement number three is long enough."
        )
        source = make_source(text)

        claims = VerbatimClaimExtractor(
            max_claims=2,
        ).extract(source, text)

        self.assertEqual(len(claims), 2)

    def test_release_check(self) -> None:
        self.assertEqual(
            claims_release_check()["safety"],
            "pass",
        )


if __name__ == "__main__":
    unittest.main()
