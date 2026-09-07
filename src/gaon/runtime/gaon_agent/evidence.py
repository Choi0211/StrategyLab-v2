"""Evidence-ingestion interface foundation (pipeline lands in PR #218).

The core principle: **learning is not the same as accepting something as
true**. An external claim ("this YouTuber says RSI<30 wins 90% of the time")
is recorded with full provenance and a ``verification_state`` of
``UNVERIFIED`` - it only becomes trusted after independent validation
against real market data.

PR #214 ships the typed domain model and a fail-closed :class:`EvidenceIngestor`
Protocol plus a :class:`NullEvidenceIngestor` that refuses everything. No
storage, no migration, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    VALIDATING = "validating"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class SourceType(str, Enum):
    URL = "url"
    VIDEO = "video"
    DOCUMENT = "document"
    IMAGE = "image"
    USER_MESSAGE = "user_message"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceRef:
    """Where an observation came from. Provenance is mandatory - an evidence
    record with no usable source reference is rejected (fail closed)."""

    source_type: SourceType
    reference: str
    retrieved_at: str
    provider: str | None = None
    content_hash: str | None = None

    @property
    def has_provenance(self) -> bool:
        return bool(self.reference.strip()) and bool(self.retrieved_at.strip())


@dataclass(frozen=True)
class Observation:
    """A raw thing that was read/seen from a source, before interpretation."""

    source: SourceRef
    excerpt: str
    extraction_method: str


@dataclass(frozen=True)
class Claim:
    """An interpreted assertion attributed to a source - phrased as *their*
    claim, never as an established fact."""

    statement: str
    attributed_to: str
    observation: Observation


@dataclass(frozen=True)
class EvidenceRecord:
    """An immutable, provenance-tagged claim awaiting independent validation."""

    claim: Claim
    verification_state: VerificationState = VerificationState.UNVERIFIED
    independent_validation_ref: str | None = None
    related_hypothesis_ref: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.claim.observation.source.has_provenance:
            raise ValueError("evidence rejected: source provenance is missing")
        if self.verification_state is VerificationState.UNVERIFIED and self.independent_validation_ref:
            raise ValueError("UNVERIFIED evidence cannot carry an independent validation reference")

    @property
    def is_trusted(self) -> bool:
        return self.verification_state is VerificationState.SUPPORTED


class EvidenceIngestionError(RuntimeError):
    pass


class EvidenceIngestor(Protocol):
    """Records an external claim as unverified evidence. Implementations must
    never mark a freshly ingested claim as trusted."""

    def ingest(self, claim: Claim) -> EvidenceRecord: ...


class NullEvidenceIngestor:
    """The only implementation in PR #214: it refuses, loudly and honestly.

    Callers get a clear signal that evidence ingestion is not wired yet
    rather than a silent success that could later be mistaken for a
    validated fact.
    """

    capability_id = "EVIDENCE_INGEST"

    def ingest(self, claim: Claim) -> EvidenceRecord:
        raise EvidenceIngestionError(
            "evidence ingestion is not available yet (planned: PR #218); "
            "the claim was not stored"
        )
