"""Sprint 169 — Knowledge Conflict Resolution Foundation.

This module detects structured evidence conflicts without pretending to
understand unsupported semantics.

Safety invariants:
- conflict detection requires an explicit topic key
- stance is explicit, never inferred from free text here
- different claims from one source are not independent corroboration
- conflict resolution never creates Validated Knowledge
- no strategy mutation, Champion promotion, KIS/Broker order, or policy change
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping

from .claims import KnowledgeCandidate


CONFLICT_SCHEMA_VERSION = 1

_TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")


class ClaimStance(str, Enum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    NEUTRAL = "neutral"


class ConflictStatus(str, Enum):
    SUPPORTED = "supported"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    INSUFFICIENT_INDEPENDENCE = "insufficient_independence"
    NO_COMPARABLE_EVIDENCE = "no_comparable_evidence"


@dataclass(frozen=True)
class PositionedClaim:
    candidate_id: str
    claim_id: str
    source_id: str
    topic_key: str
    stance: ClaimStance
    claim_text: str
    evidence_score: int
    knowledge_validated: bool = False
    production_approved: bool = False
    policy_applied: bool = False

    @classmethod
    def from_candidate(
        cls,
        candidate: KnowledgeCandidate,
        *,
        topic_key: str,
        stance: ClaimStance,
    ) -> "PositionedClaim":
        normalized_topic = topic_key.strip().lower()

        if not _TOPIC_RE.fullmatch(normalized_topic):
            raise ValueError(
                "topic_key must be a stable lowercase research identifier"
            )

        if candidate.knowledge_validated:
            raise ValueError(
                "Sprint 169 expects unvalidated knowledge candidates"
            )

        if candidate.production_approved:
            raise ValueError(
                "production-approved candidate is outside this research gate"
            )

        return cls(
            candidate_id=candidate.candidate_id,
            claim_id=candidate.claim_id,
            source_id=candidate.source_id,
            topic_key=normalized_topic,
            stance=stance,
            claim_text=candidate.claim_text,
            evidence_score=int(candidate.evidence_score),
        )


@dataclass(frozen=True)
class KnowledgeConflictRecord:
    conflict_id: str
    topic_key: str
    status: ConflictStatus
    supporting_claim_ids: tuple[str, ...]
    opposing_claim_ids: tuple[str, ...]
    neutral_claim_ids: tuple[str, ...]
    independent_source_count: int
    supporting_source_count: int
    opposing_source_count: int
    supporting_score: int
    opposing_score: int
    reasons: tuple[str, ...]
    knowledge_validated: bool = False
    production_approved: bool = False
    policy_applied: bool = False
    automatic_resolution: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": CONFLICT_SCHEMA_VERSION,
            "conflict_id": self.conflict_id,
            "topic_key": self.topic_key,
            "status": self.status.value,
            "supporting_claim_ids": list(self.supporting_claim_ids),
            "opposing_claim_ids": list(self.opposing_claim_ids),
            "neutral_claim_ids": list(self.neutral_claim_ids),
            "independent_source_count": self.independent_source_count,
            "supporting_source_count": self.supporting_source_count,
            "opposing_source_count": self.opposing_source_count,
            "supporting_score": self.supporting_score,
            "opposing_score": self.opposing_score,
            "reasons": list(self.reasons),
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "policy_applied": self.policy_applied,
            "automatic_resolution": self.automatic_resolution,
        }


def canonical_conflict_id(
    *,
    topic_key: str,
    claims: Iterable[PositionedClaim],
) -> str:
    claim_ids = sorted(item.claim_id for item in claims)

    encoded = json.dumps(
        {
            "topic_key": topic_key,
            "claim_ids": claim_ids,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return f"knowledge-conflict:{hashlib.sha256(encoded).hexdigest()}"


class KnowledgeConflictDetector:
    """Deterministic contradiction detector over structured stances."""

    def evaluate(
        self,
        topic_key: str,
        claims: Iterable[PositionedClaim],
    ) -> KnowledgeConflictRecord:
        topic = topic_key.strip().lower()
        if not _TOPIC_RE.fullmatch(topic):
            raise ValueError("invalid topic_key")

        items = tuple(claims)

        if any(item.topic_key != topic for item in items):
            raise ValueError("mixed topic claims are not comparable")

        # Stable de-duplication by claim identity.
        unique_by_claim: dict[str, PositionedClaim] = {}
        for item in items:
            existing = unique_by_claim.get(item.claim_id)
            if existing is not None and existing != item:
                raise ValueError("same claim_id has conflicting structured metadata")
            unique_by_claim[item.claim_id] = item

        unique = tuple(
            sorted(
                unique_by_claim.values(),
                key=lambda item: item.claim_id,
            )
        )

        supporting = tuple(
            item for item in unique
            if item.stance is ClaimStance.SUPPORTS
        )
        opposing = tuple(
            item for item in unique
            if item.stance is ClaimStance.OPPOSES
        )
        neutral = tuple(
            item for item in unique
            if item.stance is ClaimStance.NEUTRAL
        )

        all_sources = {item.source_id for item in unique}
        supporting_sources = {item.source_id for item in supporting}
        opposing_sources = {item.source_id for item in opposing}

        supporting_score = self._independent_score(supporting)
        opposing_score = self._independent_score(opposing)

        reasons: list[str] = []

        if not supporting and not opposing:
            status = ConflictStatus.NO_COMPARABLE_EVIDENCE
            reasons.append("no_directional_claims")

        elif supporting and opposing:
            if len(all_sources) < 2:
                status = ConflictStatus.INSUFFICIENT_INDEPENDENCE
                reasons.append(
                    "opposing_stances_exist_but_only_one_source_is_present"
                )
            elif supporting_sources == opposing_sources and len(all_sources) == 1:
                status = ConflictStatus.INSUFFICIENT_INDEPENDENCE
                reasons.append("same_source_is_not_independent_corroboration")
            else:
                status = ConflictStatus.UNRESOLVED_CONFLICT
                reasons.append(
                    "independent_sources_support_opposing_stances"
                )
                reasons.append(
                    "conflict_must_not_be_auto_resolved_by_score"
                )

        else:
            directional = supporting if supporting else opposing
            directional_sources = {item.source_id for item in directional}

            if len(directional_sources) >= 2:
                status = ConflictStatus.SUPPORTED
                reasons.append(
                    "multiple_independent_sources_share_same_direction"
                )
            else:
                status = ConflictStatus.INSUFFICIENT_INDEPENDENCE
                reasons.append(
                    "single_source_direction_requires_corroboration"
                )

        return KnowledgeConflictRecord(
            conflict_id=canonical_conflict_id(
                topic_key=topic,
                claims=unique,
            ),
            topic_key=topic,
            status=status,
            supporting_claim_ids=tuple(
                item.claim_id for item in supporting
            ),
            opposing_claim_ids=tuple(
                item.claim_id for item in opposing
            ),
            neutral_claim_ids=tuple(
                item.claim_id for item in neutral
            ),
            independent_source_count=len(all_sources),
            supporting_source_count=len(supporting_sources),
            opposing_source_count=len(opposing_sources),
            supporting_score=supporting_score,
            opposing_score=opposing_score,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _independent_score(
        claims: Iterable[PositionedClaim],
    ) -> int:
        """Use strongest evidence per source to avoid source duplication."""

        strongest_by_source: dict[str, int] = {}

        for item in claims:
            prior = strongest_by_source.get(item.source_id)
            if prior is None or item.evidence_score > prior:
                strongest_by_source[item.source_id] = item.evidence_score

        return sum(strongest_by_source.values())


def conflict_release_check() -> Mapping[str, object]:
    from .claims import (
        KnowledgeCandidate,
        KnowledgeCandidateStatus,
    )
    from .quality import EvidenceUse

    def candidate(
        suffix: str,
        source_suffix: str,
        score: int,
    ) -> KnowledgeCandidate:
        return KnowledgeCandidate(
            candidate_id=f"knowledge-candidate:{suffix}",
            claim_id=f"claim:{suffix}",
            source_id=f"source:{source_suffix}",
            claim_text=f"Research claim {suffix}",
            status=KnowledgeCandidateStatus.EVIDENCE_BACKED,
            evidence_use=EvidenceUse.PRIMARY,
            evidence_score=score,
        )

    support_a = PositionedClaim.from_candidate(
        candidate("a", "source-a", 90),
        topic_key="trend.regime.robustness",
        stance=ClaimStance.SUPPORTS,
    )

    support_b = PositionedClaim.from_candidate(
        candidate("b", "source-b", 80),
        topic_key="trend.regime.robustness",
        stance=ClaimStance.SUPPORTS,
    )

    oppose_c = PositionedClaim.from_candidate(
        candidate("c", "source-c", 85),
        topic_key="trend.regime.robustness",
        stance=ClaimStance.OPPOSES,
    )

    detector = KnowledgeConflictDetector()

    supported = detector.evaluate(
        "trend.regime.robustness",
        (support_a, support_b),
    )

    conflicted = detector.evaluate(
        "trend.regime.robustness",
        (support_a, oppose_c),
    )

    checks = {
        "independent_support_detected":
            supported.status is ConflictStatus.SUPPORTED,
        "conflict_detected":
            conflicted.status
            is ConflictStatus.UNRESOLVED_CONFLICT,
        "conflict_not_auto_resolved":
            conflicted.automatic_resolution is False,
        "support_not_validated":
            supported.knowledge_validated is False,
        "conflict_not_validated":
            conflicted.knowledge_validated is False,
        "production_not_approved":
            not supported.production_approved
            and not conflicted.production_approved,
        "policy_not_applied":
            not supported.policy_applied
            and not conflicted.policy_applied,
    }

    if not all(checks.values()):
        failed = ",".join(
            name for name, ok in checks.items() if not ok
        )
        raise RuntimeError(
            f"knowledge conflict release check failed: {failed}"
        )

    return {
        "schema_version": CONFLICT_SCHEMA_VERSION,
        "supported_status": supported.status.value,
        "conflict_status": conflicted.status.value,
        "independent_sources": conflicted.independent_source_count,
        "checks": checks,
        "safety": "pass",
    }


if __name__ == "__main__":
    payload = conflict_release_check()
    print(
        "gaon-knowledge-conflict-release-check: PASS "
        f"schema_version={payload['schema_version']} "
        f"supported={payload['supported_status']} "
        f"conflict={payload['conflict_status']} "
        f"independent_sources={payload['independent_sources']} "
        "automatic_resolution=false "
        "knowledge_validated=false "
        "production_approved=false "
        "policy_applied=false "
        "safety=pass"
    )
