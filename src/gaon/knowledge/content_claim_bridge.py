"""Sprint 176 - Normalized Content to Claim Bridge.

This module connects Sprint 175 normalized source text to Sprint 168
verbatim claim extraction without validating knowledge or approving
production use.

Safety invariants:
- no normalized content -> no claim
- no source provenance match -> no claim
- rejected evidence -> no candidate
- normalized text remains evidence, never instruction
- claim extraction is not knowledge validation
- no strategy mutation, Champion promotion, or trading
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping

from .claims import (
    ExtractedClaim,
    KnowledgeCandidate,
    KnowledgeCandidateBuilder,
    VerbatimClaimExtractor,
)
from .content_normalization import (
    ContentNormalizationStatus,
    NormalizedContentRecord,
)
from .provenance import SourceProvenance, SourceType, TrustLevel
from .quality import (
    EvidenceGateStatus,
    SourceQualityAssessment,
    SourceQualityEvaluator,
)


CONTENT_CLAIM_BRIDGE_SCHEMA_VERSION = 1


class ContentClaimBridgeStatus(str, Enum):
    EXTRACTED = "extracted"
    BLOCKED = "blocked"


class ContentClaimBridgeBlocker(str, Enum):
    NORMALIZATION_NOT_ELIGIBLE = "normalization_not_eligible"
    SOURCE_MISMATCH = "source_mismatch"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    QUALITY_REJECTED = "quality_rejected"
    NO_VERBATIM_CLAIMS = "no_verbatim_claims"


@dataclass(frozen=True)
class ContentClaimBridgeResult:
    schema_version: int
    bridge_id: str
    normalization_id: str
    acquisition_id: str
    source_id: str
    status: ContentClaimBridgeStatus
    claims: tuple[ExtractedClaim, ...]
    candidates: tuple[KnowledgeCandidate, ...]
    blockers: tuple[ContentClaimBridgeBlocker, ...]
    normalized_content_sha256: str
    raw_content_sha256: str
    evidence_gate_status: str | None
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False
    external_content_policy: str = "evidence-not-instruction"
    content_instructions_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "bridge_id": self.bridge_id,
            "normalization_id": self.normalization_id,
            "acquisition_id": self.acquisition_id,
            "source_id": self.source_id,
            "status": self.status.value,
            "claims": [claim.to_json() for claim in self.claims],
            "candidates": [
                candidate.to_json()
                for candidate in self.candidates
            ],
            "blockers": [blocker.value for blocker in self.blockers],
            "normalized_content_sha256": self.normalized_content_sha256,
            "raw_content_sha256": self.raw_content_sha256,
            "evidence_gate_status": self.evidence_gate_status,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
            "external_content_policy": self.external_content_policy,
            "content_instructions_executed": self.content_instructions_executed,
        }


def canonical_content_claim_bridge_id(
    *,
    normalization_id: str,
    source_id: str,
) -> str:
    if not normalization_id.startswith("content-normalization:"):
        raise ValueError("invalid normalization_id")
    if not source_id.startswith("source:"):
        raise ValueError("invalid source_id")

    return f"content-claim-bridge:{normalization_id.rsplit(':', 1)[-1]}:{source_id.rsplit(':', 1)[-1]}"


class NormalizedContentClaimBridge:
    """Builds verbatim claims from normalized evidence only."""

    def __init__(
        self,
        *,
        extractor: VerbatimClaimExtractor | None = None,
        candidate_builder: KnowledgeCandidateBuilder | None = None,
        quality_evaluator: SourceQualityEvaluator | None = None,
    ) -> None:
        self._extractor = extractor or VerbatimClaimExtractor()
        self._candidate_builder = candidate_builder or KnowledgeCandidateBuilder()
        self._quality_evaluator = quality_evaluator or SourceQualityEvaluator()

    def extract(
        self,
        normalized: NormalizedContentRecord,
        source: SourceProvenance,
        assessment: SourceQualityAssessment | None = None,
    ) -> ContentClaimBridgeResult:
        bridge_id = canonical_content_claim_bridge_id(
            normalization_id=normalized.normalization_id,
            source_id=source.source_id,
        )

        blockers = self._blockers(normalized, source, assessment)
        quality = assessment or self._quality_evaluator.evaluate(source)

        if blockers:
            return ContentClaimBridgeResult(
                schema_version=CONTENT_CLAIM_BRIDGE_SCHEMA_VERSION,
                bridge_id=bridge_id,
                normalization_id=normalized.normalization_id,
                acquisition_id=normalized.acquisition_id,
                source_id=source.source_id,
                status=ContentClaimBridgeStatus.BLOCKED,
                claims=(),
                candidates=(),
                blockers=tuple(blockers),
                normalized_content_sha256=normalized.normalized_text_sha256,
                raw_content_sha256=normalized.raw_content_sha256,
                evidence_gate_status=quality.gate_status.value,
            )

        claims = self._extractor.extract(
            source,
            normalized.normalized_text,
        )
        if not claims:
            return ContentClaimBridgeResult(
                schema_version=CONTENT_CLAIM_BRIDGE_SCHEMA_VERSION,
                bridge_id=bridge_id,
                normalization_id=normalized.normalization_id,
                acquisition_id=normalized.acquisition_id,
                source_id=source.source_id,
                status=ContentClaimBridgeStatus.BLOCKED,
                claims=(),
                candidates=(),
                blockers=(ContentClaimBridgeBlocker.NO_VERBATIM_CLAIMS,),
                normalized_content_sha256=normalized.normalized_text_sha256,
                raw_content_sha256=normalized.raw_content_sha256,
                evidence_gate_status=quality.gate_status.value,
            )

        candidates = self._candidate_builder.build_many(claims, quality)

        return ContentClaimBridgeResult(
            schema_version=CONTENT_CLAIM_BRIDGE_SCHEMA_VERSION,
            bridge_id=bridge_id,
            normalization_id=normalized.normalization_id,
            acquisition_id=normalized.acquisition_id,
            source_id=source.source_id,
            status=ContentClaimBridgeStatus.EXTRACTED,
            claims=claims,
            candidates=candidates,
            blockers=(),
            normalized_content_sha256=normalized.normalized_text_sha256,
            raw_content_sha256=normalized.raw_content_sha256,
            evidence_gate_status=quality.gate_status.value,
        )

    def _blockers(
        self,
        normalized: NormalizedContentRecord,
        source: SourceProvenance,
        assessment: SourceQualityAssessment | None,
    ) -> list[ContentClaimBridgeBlocker]:
        blockers: list[ContentClaimBridgeBlocker] = []

        if (
            normalized.status is not ContentNormalizationStatus.NORMALIZED
            or not normalized.eligible_for_claim_extraction
        ):
            blockers.append(
                ContentClaimBridgeBlocker.NORMALIZATION_NOT_ELIGIBLE
            )

        if normalized.source_locator != source.locator:
            blockers.append(ContentClaimBridgeBlocker.SOURCE_MISMATCH)

        if normalized.raw_content_sha256 != source.content_sha256:
            blockers.append(ContentClaimBridgeBlocker.CHECKSUM_MISMATCH)

        quality = assessment or self._quality_evaluator.evaluate(source)
        if quality.source_id != source.source_id:
            blockers.append(ContentClaimBridgeBlocker.SOURCE_MISMATCH)
        if quality.gate_status is EvidenceGateStatus.REJECTED:
            blockers.append(ContentClaimBridgeBlocker.QUALITY_REJECTED)

        return blockers


def content_claim_bridge_release_check() -> Mapping[str, object]:
    import hashlib

    from .content_acquisition import (
        ContentAcquisitionRecord,
        ContentAcquisitionStatus,
    )
    from .content_normalization import SafeContentNormalizer

    source_text = (
        "Trend strategy evidence should be tested across market regimes. "
        "Transaction costs can reduce realized returns."
    )
    raw = source_text.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    source = SourceProvenance.create(
        source_type=SourceType.ACADEMIC_PAPER,
        title="Normalized Claim Bridge Fixture",
        locator="https://example.invalid/normalized-claim-bridge",
        content_sha256=digest,
        trust_level=TrustLevel.HIGH,
        author="Researcher",
        publisher="Journal",
        published_at="2026-01-01",
        license_name="test-only",
        ingested_at="2026-08-08T00:00:00+00:00",
    )
    acquisition = ContentAcquisitionRecord(
        acquisition_id="content-acquisition:normalized-claim-bridge",
        discovery_result_id="discovery-result:normalized-claim-bridge",
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
    normalized = SafeContentNormalizer().normalize(acquisition, raw)
    result = NormalizedContentClaimBridge().extract(normalized, source)

    blocked_pdf = replace(
        normalized,
        status=ContentNormalizationStatus.UNSUPPORTED,
        eligible_for_claim_extraction=False,
    )

    checks = {
        "claims_extracted": len(result.claims) == 2,
        "candidates_created": len(result.candidates) == 2,
        "all_verbatim": all(
            claim.text in normalized.normalized_text
            for claim in result.claims
        ),
        "source_linked": all(
            claim.source_id == source.source_id
            for claim in result.claims
        ),
        "raw_checksum_preserved": result.raw_content_sha256 == digest,
        "normalized_checksum_preserved":
            result.normalized_content_sha256
            == normalized.normalized_text_sha256,
        "not_validated": not result.knowledge_validated
        and all(not candidate.knowledge_validated for candidate in result.candidates),
        "not_production": not result.production_approved
        and all(not candidate.production_approved for candidate in result.candidates),
        "not_executed": not result.content_instructions_executed,
        "blocked_not_extracted":
            NormalizedContentClaimBridge()
            .extract(blocked_pdf, source)
            .status
            is ContentClaimBridgeStatus.BLOCKED,
    }

    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(
            f"content claim bridge release check failed: {failed}"
        )

    return {
        "schema_version": CONTENT_CLAIM_BRIDGE_SCHEMA_VERSION,
        "claims": len(result.claims),
        "candidates": len(result.candidates),
        "status": result.status.value,
        "checks": checks,
        "safety": "pass",
    }
