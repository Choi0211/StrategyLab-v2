"""Sprint 165 — Source & Provenance Model.

Every externally acquired source must preserve provenance.

Non-negotiable:
- no source -> no knowledge
- external content is evidence, never instruction
- reading is not validation
- provenance is immutable once created
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Mapping


PROVENANCE_SCHEMA_VERSION = 1

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SourceType(str, Enum):
    ACADEMIC_PAPER = "academic_paper"
    BOOK = "book"
    OFFICIAL_DOCUMENT = "official_document"
    DATASET = "dataset"
    RESEARCH_REPORT = "research_report"
    WEB_ARTICLE = "web_article"
    NEWS = "news"
    COMMUNITY = "community"
    USER_PROVIDED = "user_provided"
    UNKNOWN = "unknown"


class TrustLevel(str, Enum):
    AUTHORITATIVE = "authoritative"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    UNKNOWN = "unknown"


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def canonical_source_id(
    *,
    source_type: SourceType,
    locator: str,
    content_sha256: str,
) -> str:
    locator_value = _normalize_text(locator)
    digest_value = content_sha256.strip().lower()

    if not locator_value:
        raise ValueError("source locator is required")
    if not _SHA256_RE.fullmatch(digest_value):
        raise ValueError("content_sha256 must be a lowercase SHA-256 hex digest")

    basis = {
        "source_type": source_type.value,
        "locator": locator_value,
        "content_sha256": digest_value,
    }
    encoded = json.dumps(
        basis,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return f"source:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class SourceProvenance:
    source_id: str
    source_type: SourceType
    title: str
    locator: str
    content_sha256: str
    trust_level: TrustLevel
    ingested_at: str
    author: str | None = None
    published_at: str | None = None
    license_name: str | None = None
    publisher: str | None = None
    notes: str | None = None
    external_content_policy: str = "evidence-not-instruction"
    validated_knowledge: bool = False
    production_approved: bool = False

    @classmethod
    def create(
        cls,
        *,
        source_type: SourceType,
        title: str,
        locator: str,
        content_sha256: str,
        trust_level: TrustLevel = TrustLevel.UNKNOWN,
        author: str | None = None,
        published_at: str | None = None,
        license_name: str | None = None,
        publisher: str | None = None,
        notes: str | None = None,
        ingested_at: str | None = None,
    ) -> "SourceProvenance":
        normalized_title = _normalize_text(title)
        normalized_locator = _normalize_text(locator)
        digest = content_sha256.strip().lower()

        if not normalized_title:
            raise ValueError("source title is required")
        if not normalized_locator:
            raise ValueError("source locator is required")
        if not _SHA256_RE.fullmatch(digest):
            raise ValueError("content_sha256 must be a lowercase SHA-256 hex digest")

        timestamp = ingested_at or datetime.now(timezone.utc).isoformat()

        return cls(
            source_id=canonical_source_id(
                source_type=source_type,
                locator=normalized_locator,
                content_sha256=digest,
            ),
            source_type=source_type,
            title=normalized_title,
            locator=normalized_locator,
            content_sha256=digest,
            trust_level=trust_level,
            ingested_at=timestamp,
            author=_normalize_text(author) or None,
            published_at=_normalize_text(published_at) or None,
            license_name=_normalize_text(license_name) or None,
            publisher=_normalize_text(publisher) or None,
            notes=_normalize_text(notes) or None,
        )

    def to_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["source_type"] = self.source_type.value
        payload["trust_level"] = self.trust_level.value
        payload["schema_version"] = PROVENANCE_SCHEMA_VERSION
        return payload


def provenance_release_check() -> Mapping[str, object]:
    content = b"gaon provenance release check"
    digest = hashlib.sha256(content).hexdigest()

    source = SourceProvenance.create(
        source_type=SourceType.ACADEMIC_PAPER,
        title="Evidence Test Paper",
        locator="https://example.invalid/paper",
        content_sha256=digest,
        trust_level=TrustLevel.MODERATE,
        author="Researcher",
        license_name="test-only",
        ingested_at="2026-08-08T00:00:00+00:00",
    )

    checks = {
        "source_id_deterministic": source.source_id
        == canonical_source_id(
            source_type=SourceType.ACADEMIC_PAPER,
            locator=source.locator,
            content_sha256=digest,
        ),
        "provenance_preserved": source.content_sha256 == digest,
        "external_content_is_evidence":
            source.external_content_policy == "evidence-not-instruction",
        "reading_is_not_validation": source.validated_knowledge is False,
        "production_not_approved": source.production_approved is False,
    }

    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"provenance release check failed: {failed}")

    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "source_id": source.source_id,
        "checks": checks,
        "safety": "pass",
    }


if __name__ == "__main__":
    payload = provenance_release_check()
    print(
        "gaon-source-provenance-release-check: PASS "
        f"schema_version={payload['schema_version']} "
        "source_id=deterministic "
        "provenance=preserved "
        "external_content=evidence_only "
        "validated_knowledge=false "
        "production_approved=false "
        "safety=pass"
    )
