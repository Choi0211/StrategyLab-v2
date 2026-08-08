"""Sprint 168 — Claim Extraction & Knowledge Candidate Foundation.

This module converts source text into provenance-linked claim records.

Safety invariants:
- extracted claims must exist verbatim in supplied source text
- no fabricated claims
- no claim without source provenance
- rejected evidence cannot become a knowledge candidate
- claim extraction is not knowledge validation
- knowledge candidate is not strategy approval
- no Champion promotion or live trading
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping

from .provenance import SourceProvenance
from .quality import (
    EvidenceGateStatus,
    EvidenceUse,
    SourceQualityAssessment,
)


CLAIM_SCHEMA_VERSION = 1

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_SPACE_RE = re.compile(r"\s+")


def _normalize_claim_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip())


def canonical_claim_id(*, source_id: str, text: str) -> str:
    normalized = _normalize_claim_text(text)
    if not source_id.startswith("source:"):
        raise ValueError("invalid source_id")
    if not normalized:
        raise ValueError("claim text is required")

    encoded = json.dumps(
        {
            "source_id": source_id,
            "text": normalized,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return f"claim:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class EvidenceLink:
    source_id: str
    claim_id: str
    source_content_sha256: str
    claim_text_sha256: str
    locator: str

    def to_json(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "claim_id": self.claim_id,
            "source_content_sha256": self.source_content_sha256,
            "claim_text_sha256": self.claim_text_sha256,
            "locator": self.locator,
        }


@dataclass(frozen=True)
class ExtractedClaim:
    claim_id: str
    source_id: str
    text: str
    ordinal: int
    evidence_link: EvidenceLink
    verbatim_from_source: bool = True
    knowledge_validated: bool = False
    production_approved: bool = False
    executable: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": CLAIM_SCHEMA_VERSION,
            "claim_id": self.claim_id,
            "source_id": self.source_id,
            "text": self.text,
            "ordinal": self.ordinal,
            "evidence_link": self.evidence_link.to_json(),
            "verbatim_from_source": self.verbatim_from_source,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "executable": self.executable,
        }


class KnowledgeCandidateStatus(str, Enum):
    EVIDENCE_BACKED = "evidence_backed"
    LIMITED_EVIDENCE = "limited_evidence"


@dataclass(frozen=True)
class KnowledgeCandidate:
    candidate_id: str
    claim_id: str
    source_id: str
    claim_text: str
    status: KnowledgeCandidateStatus
    evidence_use: EvidenceUse
    evidence_score: int
    knowledge_validated: bool = False
    research_tested: bool = False
    production_approved: bool = False
    policy_applied: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": CLAIM_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "claim_id": self.claim_id,
            "source_id": self.source_id,
            "claim_text": self.claim_text,
            "status": self.status.value,
            "evidence_use": self.evidence_use.value,
            "evidence_score": self.evidence_score,
            "knowledge_validated": self.knowledge_validated,
            "research_tested": self.research_tested,
            "production_approved": self.production_approved,
            "policy_applied": self.policy_applied,
        }


class VerbatimClaimExtractor:
    """Deterministically extracts source-present text segments only.

    This is deliberately conservative. It does not summarize, paraphrase,
    infer, or use an LLM.
    """

    def __init__(
        self,
        *,
        min_chars: int = 12,
        max_claims: int = 100,
    ) -> None:
        if min_chars <= 0:
            raise ValueError("min_chars must be positive")
        if max_claims <= 0:
            raise ValueError("max_claims must be positive")
        self.min_chars = min_chars
        self.max_claims = max_claims

    def extract(
        self,
        source: SourceProvenance,
        source_text: str,
    ) -> tuple[ExtractedClaim, ...]:
        if not isinstance(source_text, str):
            raise TypeError("source_text must be str")
        if not source_text.strip():
            raise ValueError("source_text is empty")

        raw_segments = _SENTENCE_SPLIT_RE.split(source_text)

        claims: list[ExtractedClaim] = []
        seen: set[str] = set()

        for raw in raw_segments:
            text = _normalize_claim_text(raw)
            if len(text) < self.min_chars:
                continue

            # The normalized claim must be derivable only from the supplied text.
            if text in seen:
                continue

            claim_id = canonical_claim_id(
                source_id=source.source_id,
                text=text,
            )
            text_digest = hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest()

            link = EvidenceLink(
                source_id=source.source_id,
                claim_id=claim_id,
                source_content_sha256=source.content_sha256,
                claim_text_sha256=text_digest,
                locator=source.locator,
            )

            claims.append(
                ExtractedClaim(
                    claim_id=claim_id,
                    source_id=source.source_id,
                    text=text,
                    ordinal=len(claims),
                    evidence_link=link,
                )
            )
            seen.add(text)

            if len(claims) >= self.max_claims:
                break

        return tuple(claims)


def canonical_candidate_id(
    *,
    claim_id: str,
    source_id: str,
) -> str:
    if not claim_id.startswith("claim:"):
        raise ValueError("invalid claim_id")
    if not source_id.startswith("source:"):
        raise ValueError("invalid source_id")

    encoded = json.dumps(
        {
            "claim_id": claim_id,
            "source_id": source_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return f"knowledge-candidate:{hashlib.sha256(encoded).hexdigest()}"


class KnowledgeCandidateBuilder:
    """Promotes eligible claims only to unvalidated Knowledge Candidates."""

    def build(
        self,
        claim: ExtractedClaim,
        assessment: SourceQualityAssessment,
    ) -> KnowledgeCandidate:
        if claim.source_id != assessment.source_id:
            raise ValueError("claim/source quality provenance mismatch")

        if not claim.verbatim_from_source:
            raise ValueError("non-verbatim claim is not eligible")

        if assessment.gate_status is EvidenceGateStatus.REJECTED:
            raise ValueError("rejected evidence cannot create knowledge candidate")

        if assessment.evidence_use is EvidenceUse.BLOCKED:
            raise ValueError("blocked evidence cannot create knowledge candidate")

        if assessment.gate_status is EvidenceGateStatus.ACCEPTED:
            status = KnowledgeCandidateStatus.EVIDENCE_BACKED
        else:
            status = KnowledgeCandidateStatus.LIMITED_EVIDENCE

        return KnowledgeCandidate(
            candidate_id=canonical_candidate_id(
                claim_id=claim.claim_id,
                source_id=claim.source_id,
            ),
            claim_id=claim.claim_id,
            source_id=claim.source_id,
            claim_text=claim.text,
            status=status,
            evidence_use=assessment.evidence_use,
            evidence_score=assessment.score,
        )

    def build_many(
        self,
        claims: Iterable[ExtractedClaim],
        assessment: SourceQualityAssessment,
    ) -> tuple[KnowledgeCandidate, ...]:
        return tuple(
            self.build(claim, assessment)
            for claim in claims
        )


def claims_release_check() -> Mapping[str, object]:
    import hashlib

    from .provenance import SourceType, TrustLevel
    from .quality import SourceQualityEvaluator

    source_text = (
        "Trend following performance can vary across market regimes. "
        "Transaction costs may reduce observed strategy returns. "
        "A backtest result does not guarantee future performance."
    )

    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    source = SourceProvenance.create(
        source_type=SourceType.ACADEMIC_PAPER,
        title="Claim Extraction Test",
        locator="https://example.invalid/claim-test",
        content_sha256=digest,
        trust_level=TrustLevel.HIGH,
        author="Researcher",
        publisher="Journal",
        published_at="2026-01-01",
        license_name="test-only",
        ingested_at="2026-08-08T00:00:00+00:00",
    )

    assessment = SourceQualityEvaluator().evaluate(source)
    claims = VerbatimClaimExtractor().extract(source, source_text)
    candidates = KnowledgeCandidateBuilder().build_many(
        claims,
        assessment,
    )

    checks = {
        "claims_extracted": len(claims) == 3,
        "all_verbatim": all(
            claim.text in source_text
            for claim in claims
        ),
        "source_linked": all(
            claim.source_id == source.source_id
            for claim in claims
        ),
        "checksum_linked": all(
            claim.evidence_link.source_content_sha256
            == source.content_sha256
            for claim in claims
        ),
        "candidate_count_matches": len(candidates) == len(claims),
        "candidate_unvalidated": all(
            not candidate.knowledge_validated
            for candidate in candidates
        ),
        "candidate_untested": all(
            not candidate.research_tested
            for candidate in candidates
        ),
        "candidate_not_production": all(
            not candidate.production_approved
            for candidate in candidates
        ),
        "policy_not_applied": all(
            not candidate.policy_applied
            for candidate in candidates
        ),
    }

    if not all(checks.values()):
        failed = ",".join(
            name for name, ok in checks.items() if not ok
        )
        raise RuntimeError(
            f"claim extraction release check failed: {failed}"
        )

    return {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "claims": len(claims),
        "candidates": len(candidates),
        "status": candidates[0].status.value,
        "checks": checks,
        "safety": "pass",
    }


if __name__ == "__main__":
    payload = claims_release_check()
    print(
        "gaon-claim-knowledge-candidate-release-check: PASS "
        f"schema_version={payload['schema_version']} "
        f"claims={payload['claims']} "
        f"candidates={payload['candidates']} "
        f"status={payload['status']} "
        "verbatim=true "
        "knowledge_validated=false "
        "research_tested=false "
        "production_approved=false "
        "policy_applied=false "
        "safety=pass"
    )
