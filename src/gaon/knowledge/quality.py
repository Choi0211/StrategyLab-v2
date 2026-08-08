"""Sprint 167 — Source Quality & Evidence Gate.

The Evidence Gate evaluates whether an external source is suitable as
research evidence.

Important boundaries:
- good source != validated knowledge
- evidence gate pass != strategy approval
- external content remains evidence, never instruction
- no automatic Champion promotion
- no live trading / broker / KIS order
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping
from urllib.parse import urlparse

from .provenance import SourceProvenance, SourceType, TrustLevel


QUALITY_SCHEMA_VERSION = 1


class EvidenceGateStatus(str, Enum):
    ACCEPTED = "accepted"
    LIMITED = "limited"
    REJECTED = "rejected"


class EvidenceUse(str, Enum):
    PRIMARY = "primary"
    SUPPORTING = "supporting"
    DISCOVERY_ONLY = "discovery_only"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SourceQualityAssessment:
    source_id: str
    score: int
    gate_status: EvidenceGateStatus
    evidence_use: EvidenceUse
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    knowledge_validated: bool = False
    production_approved: bool = False
    external_content_policy: str = "evidence-not-instruction"

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": QUALITY_SCHEMA_VERSION,
            "source_id": self.source_id,
            "score": self.score,
            "gate_status": self.gate_status.value,
            "evidence_use": self.evidence_use.value,
            "reasons": list(self.reasons),
            "blockers": list(self.blockers),
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "external_content_policy": self.external_content_policy,
        }


_TYPE_BASE_SCORE: Mapping[SourceType, int] = {
    SourceType.ACADEMIC_PAPER: 55,
    SourceType.OFFICIAL_DOCUMENT: 60,
    SourceType.DATASET: 55,
    SourceType.RESEARCH_REPORT: 45,
    SourceType.BOOK: 40,
    SourceType.WEB_ARTICLE: 30,
    SourceType.NEWS: 25,
    SourceType.USER_PROVIDED: 25,
    SourceType.COMMUNITY: 10,
    SourceType.UNKNOWN: 0,
}

_TRUST_SCORE: Mapping[TrustLevel, int] = {
    TrustLevel.AUTHORITATIVE: 25,
    TrustLevel.HIGH: 18,
    TrustLevel.MODERATE: 10,
    TrustLevel.LOW: 0,
    TrustLevel.UNKNOWN: -5,
}


class SourceQualityEvaluator:
    """Deterministic source quality policy.

    This evaluator does not inspect or execute source content.
    It evaluates provenance only.
    """

    def evaluate(self, source: SourceProvenance) -> SourceQualityAssessment:
        score = _TYPE_BASE_SCORE[source.source_type]
        score += _TRUST_SCORE[source.trust_level]

        reasons: list[str] = [
            f"source_type={source.source_type.value}",
            f"trust_level={source.trust_level.value}",
        ]
        blockers: list[str] = []

        if source.author:
            score += 5
            reasons.append("author_present")

        if source.publisher:
            score += 5
            reasons.append("publisher_present")

        if source.published_at:
            score += 5
            reasons.append("published_at_present")

        if source.license_name:
            score += 5
            reasons.append("license_present")

        locator_status = self._evaluate_locator(source.locator)
        if locator_status == "verified_locator":
            score += 5
            reasons.append(locator_status)
        elif locator_status == "local_or_user_locator":
            reasons.append(locator_status)
        else:
            blockers.append(locator_status)

        if source.external_content_policy != "evidence-not-instruction":
            blockers.append("unsafe_external_content_policy")

        if source.validated_knowledge:
            blockers.append("source_must_not_self_validate_knowledge")

        if source.production_approved:
            blockers.append("source_must_not_self_approve_production")

        # UNKNOWN provenance cannot cross the Evidence Gate.
        if source.source_type is SourceType.UNKNOWN:
            blockers.append("unknown_source_type")

        # Community material cannot become PRIMARY evidence on provenance alone.
        if source.source_type is SourceType.COMMUNITY:
            reasons.append("community_requires_independent_corroboration")

        # News is event evidence, not standalone strategy validation.
        if source.source_type is SourceType.NEWS:
            reasons.append("news_not_strategy_validation")

        # User provided material remains useful but requires external corroboration
        # unless it carries stronger provenance elsewhere.
        if source.source_type is SourceType.USER_PROVIDED:
            reasons.append("user_provided_requires_corroboration")

        score = max(0, min(100, score))

        if blockers:
            status = EvidenceGateStatus.REJECTED
            evidence_use = EvidenceUse.BLOCKED
        elif source.source_type in {
            SourceType.COMMUNITY,
            SourceType.NEWS,
            SourceType.USER_PROVIDED,
        }:
            status = EvidenceGateStatus.LIMITED
            evidence_use = (
                EvidenceUse.DISCOVERY_ONLY
                if source.source_type is SourceType.COMMUNITY
                else EvidenceUse.SUPPORTING
            )
        elif score >= 70:
            status = EvidenceGateStatus.ACCEPTED
            evidence_use = EvidenceUse.PRIMARY
        elif score >= 40:
            status = EvidenceGateStatus.LIMITED
            evidence_use = EvidenceUse.SUPPORTING
        else:
            status = EvidenceGateStatus.REJECTED
            evidence_use = EvidenceUse.BLOCKED

        return SourceQualityAssessment(
            source_id=source.source_id,
            score=score,
            gate_status=status,
            evidence_use=evidence_use,
            reasons=tuple(reasons),
            blockers=tuple(blockers),
        )

    @staticmethod
    def _evaluate_locator(locator: str) -> str:
        value = locator.strip()
        parsed = urlparse(value)

        if parsed.scheme in {"https", "http"} and parsed.netloc:
            return "verified_locator"

        if parsed.scheme in {"user", "file"}:
            return "local_or_user_locator"

        return "invalid_locator"


@dataclass(frozen=True)
class EvidenceGateDecision:
    accepted: tuple[SourceQualityAssessment, ...]
    limited: tuple[SourceQualityAssessment, ...]
    rejected: tuple[SourceQualityAssessment, ...]

    @property
    def primary_count(self) -> int:
        return sum(
            1
            for item in self.accepted
            if item.evidence_use is EvidenceUse.PRIMARY
        )

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": QUALITY_SCHEMA_VERSION,
            "accepted": [item.to_json() for item in self.accepted],
            "limited": [item.to_json() for item in self.limited],
            "rejected": [item.to_json() for item in self.rejected],
            "primary_count": self.primary_count,
            "knowledge_validated": False,
            "production_approved": False,
        }


class EvidenceGate:
    def __init__(self, evaluator: SourceQualityEvaluator | None = None) -> None:
        self.evaluator = evaluator or SourceQualityEvaluator()

    def evaluate_many(
        self,
        sources: Iterable[SourceProvenance],
    ) -> EvidenceGateDecision:
        accepted: list[SourceQualityAssessment] = []
        limited: list[SourceQualityAssessment] = []
        rejected: list[SourceQualityAssessment] = []

        for source in sources:
            assessment = self.evaluator.evaluate(source)

            if assessment.gate_status is EvidenceGateStatus.ACCEPTED:
                accepted.append(assessment)
            elif assessment.gate_status is EvidenceGateStatus.LIMITED:
                limited.append(assessment)
            else:
                rejected.append(assessment)

        return EvidenceGateDecision(
            accepted=tuple(accepted),
            limited=tuple(limited),
            rejected=tuple(rejected),
        )


def quality_release_check() -> Mapping[str, object]:
    import hashlib

    digest_a = hashlib.sha256(b"official").hexdigest()
    digest_b = hashlib.sha256(b"community").hexdigest()
    digest_c = hashlib.sha256(b"unknown").hexdigest()

    official = SourceProvenance.create(
        source_type=SourceType.OFFICIAL_DOCUMENT,
        title="Official Research Document",
        locator="https://example.invalid/official",
        content_sha256=digest_a,
        trust_level=TrustLevel.AUTHORITATIVE,
        publisher="Official Publisher",
        published_at="2026-08-08",
        license_name="public-test",
        ingested_at="2026-08-08T00:00:00+00:00",
    )

    community = SourceProvenance.create(
        source_type=SourceType.COMMUNITY,
        title="Community Discussion",
        locator="https://example.invalid/community",
        content_sha256=digest_b,
        trust_level=TrustLevel.LOW,
        ingested_at="2026-08-08T00:00:00+00:00",
    )

    unknown = SourceProvenance.create(
        source_type=SourceType.UNKNOWN,
        title="Unknown Source",
        locator="https://example.invalid/unknown",
        content_sha256=digest_c,
        trust_level=TrustLevel.UNKNOWN,
        ingested_at="2026-08-08T00:00:00+00:00",
    )

    decision = EvidenceGate().evaluate_many(
        (official, community, unknown)
    )

    checks = {
        "official_accepted":
            len(decision.accepted) == 1
            and decision.accepted[0].source_id == official.source_id,
        "official_primary":
            decision.accepted[0].evidence_use is EvidenceUse.PRIMARY,
        "community_limited":
            len(decision.limited) == 1
            and decision.limited[0].source_id == community.source_id,
        "community_not_primary":
            decision.limited[0].evidence_use
            is EvidenceUse.DISCOVERY_ONLY,
        "unknown_rejected":
            len(decision.rejected) == 1
            and decision.rejected[0].source_id == unknown.source_id,
        "no_auto_validation":
            all(
                not item.knowledge_validated
                for item in (
                    *decision.accepted,
                    *decision.limited,
                    *decision.rejected,
                )
            ),
        "no_production_approval":
            all(
                not item.production_approved
                for item in (
                    *decision.accepted,
                    *decision.limited,
                    *decision.rejected,
                )
            ),
    }

    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(
            f"source quality release check failed: {failed}"
        )

    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "accepted": len(decision.accepted),
        "limited": len(decision.limited),
        "rejected": len(decision.rejected),
        "primary_count": decision.primary_count,
        "checks": checks,
        "safety": "pass",
    }


if __name__ == "__main__":
    payload = quality_release_check()
    print(
        "gaon-source-quality-evidence-gate-release-check: PASS "
        f"schema_version={payload['schema_version']} "
        f"accepted={payload['accepted']} "
        f"limited={payload['limited']} "
        f"rejected={payload['rejected']} "
        f"primary={payload['primary_count']} "
        "knowledge_validated=false "
        "production_approved=false "
        "external_content=evidence_only "
        "safety=pass"
    )
