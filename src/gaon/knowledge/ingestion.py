"""Sprint 166 — Knowledge Acquisition Foundation.

This module stores user/provider supplied source bytes plus provenance.
It does NOT browse the web yet.

External bytes are stored as inert evidence and are never executed.
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping

from gaon.storage.foundation import GaonStorage
from .provenance import SourceProvenance, SourceType, TrustLevel


INGESTION_SCHEMA_VERSION = 1
DEFAULT_MAX_SOURCE_BYTES = 25 * 1024 * 1024

_SAFE_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


@dataclass(frozen=True)
class IngestionResult:
    source: SourceProvenance
    raw_path: str
    metadata_path: str
    byte_count: int
    duplicate: bool
    status: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": INGESTION_SCHEMA_VERSION,
            "source": self.source.to_json(),
            "raw_path": self.raw_path,
            "metadata_path": self.metadata_path,
            "byte_count": self.byte_count,
            "duplicate": self.duplicate,
            "status": self.status,
        }


class KnowledgeIngestor:
    def __init__(
        self,
        storage: GaonStorage | None = None,
        *,
        max_source_bytes: int | None = None,
    ) -> None:
        self.storage = storage or GaonStorage()
        configured = os.environ.get("GAON_MAX_SOURCE_BYTES", "").strip()

        if max_source_bytes is not None:
            limit = int(max_source_bytes)
        elif configured:
            limit = int(configured)
        else:
            limit = DEFAULT_MAX_SOURCE_BYTES

        if limit <= 0:
            raise ValueError("max_source_bytes must be positive")

        self.max_source_bytes = limit

    def ingest_bytes(
        self,
        content: bytes,
        *,
        source_type: SourceType,
        title: str,
        locator: str,
        trust_level: TrustLevel = TrustLevel.UNKNOWN,
        author: str | None = None,
        published_at: str | None = None,
        license_name: str | None = None,
        publisher: str | None = None,
        notes: str | None = None,
        suffix: str = ".bin",
    ) -> IngestionResult:
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")
        if not content:
            raise ValueError("empty source content is not allowed")
        if len(content) > self.max_source_bytes:
            raise ValueError(
                f"source exceeds maximum size: {len(content)} > "
                f"{self.max_source_bytes}"
            )

        suffix_value = suffix.lower().strip()
        if not _SAFE_SUFFIX_RE.fullmatch(suffix_value):
            suffix_value = ".bin"

        self.storage.initialize()

        digest = hashlib.sha256(content).hexdigest()
        source = SourceProvenance.create(
            source_type=source_type,
            title=title,
            locator=locator,
            content_sha256=digest,
            trust_level=trust_level,
            author=author,
            published_at=published_at,
            license_name=license_name,
            publisher=publisher,
            notes=notes,
        )

        raw_dir = self.storage.root / "evidence" / "raw"
        metadata_dir = self.storage.root / "index" / "sources"
        raw_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)

        safe_id = source.source_id.replace(":", "_")
        raw_path = raw_dir / f"{safe_id}{suffix_value}"
        metadata_path = metadata_dir / f"{safe_id}.json"

        duplicate = raw_path.exists() and metadata_path.exists()

        if not raw_path.exists():
            tmp_raw = raw_path.with_suffix(raw_path.suffix + ".tmp")
            tmp_raw.write_bytes(content)
            os.replace(tmp_raw, raw_path)

        payload = {
            "schema_version": INGESTION_SCHEMA_VERSION,
            "source": source.to_json(),
            "raw_path": str(raw_path.relative_to(self.storage.root)),
            "byte_count": len(content),
            "content_policy": "untrusted-evidence-only",
            "executable": False,
            "knowledge_validated": False,
            "production_approved": False,
        }

        if not metadata_path.exists():
            tmp_meta = metadata_path.with_suffix(".json.tmp")
            tmp_meta.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp_meta, metadata_path)

        return IngestionResult(
            source=source,
            raw_path=str(raw_path),
            metadata_path=str(metadata_path),
            byte_count=len(content),
            duplicate=duplicate,
            status="duplicate_skipped" if duplicate else "stored",
        )

    def read_metadata(self, source_id: str) -> Mapping[str, object]:
        if not source_id.startswith("source:"):
            raise ValueError("invalid source_id")

        safe_id = source_id.replace(":", "_")
        metadata_path = (
            self.storage.root / "index" / "sources" / f"{safe_id}.json"
        )

        if not metadata_path.is_file():
            raise FileNotFoundError(source_id)

        return json.loads(metadata_path.read_text(encoding="utf-8"))


def ingestion_release_check(root: str | Path | None = None) -> Mapping[str, object]:
    storage = GaonStorage(root)
    ingestor = KnowledgeIngestor(
        storage,
        max_source_bytes=1024 * 1024,
    )

    content = b"Gaon external evidence acquisition release check"

    first = ingestor.ingest_bytes(
        content,
        source_type=SourceType.OFFICIAL_DOCUMENT,
        title="Gaon Test Official Document",
        locator="https://example.invalid/official",
        trust_level=TrustLevel.AUTHORITATIVE,
        license_name="test-only",
        suffix=".txt",
    )

    second = ingestor.ingest_bytes(
        content,
        source_type=SourceType.OFFICIAL_DOCUMENT,
        title="Gaon Test Official Document",
        locator="https://example.invalid/official",
        trust_level=TrustLevel.AUTHORITATIVE,
        license_name="test-only",
        suffix=".txt",
    )

    metadata = ingestor.read_metadata(first.source.source_id)

    checks = {
        "stored": first.status == "stored",
        "duplicate_idempotent":
            second.status == "duplicate_skipped" and second.duplicate,
        "same_source_id":
            first.source.source_id == second.source.source_id,
        "raw_exists": Path(first.raw_path).is_file(),
        "metadata_exists": Path(first.metadata_path).is_file(),
        "checksum_preserved":
            metadata["source"]["content_sha256"]
            == hashlib.sha256(content).hexdigest(),
        "external_content_untrusted":
            metadata["content_policy"] == "untrusted-evidence-only",
        "not_executable": metadata["executable"] is False,
        "not_validated": metadata["knowledge_validated"] is False,
        "not_production_approved":
            metadata["production_approved"] is False,
    }

    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"ingestion release check failed: {failed}")

    return {
        "schema_version": INGESTION_SCHEMA_VERSION,
        "source_id": first.source.source_id,
        "checks": checks,
        "safety": "pass",
    }


def _main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m gaon.knowledge.ingestion"
    )
    parser.add_argument(
        "command",
        choices=("release-check",),
    )
    parser.add_argument("--root", default=None)
    args = parser.parse_args()

    payload = ingestion_release_check(args.root)

    print(
        "gaon-knowledge-ingestion-release-check: PASS "
        f"schema_version={payload['schema_version']} "
        "source_id=stable "
        "duplicate=idempotent "
        "checksum=preserved "
        "external_content=untrusted_evidence_only "
        "executable=false "
        "knowledge_validated=false "
        "production_approved=false "
        "safety=pass"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
