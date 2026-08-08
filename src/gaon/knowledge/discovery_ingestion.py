"""Sprint 173 — Discovery → Provenance → Ingestion Bridge.

Persists Sprint 172 discovery metadata as inert evidence.

Critical boundary:
A DiscoveryResult is metadata about a possible source.
It is NOT the paper/report/dataset body itself.

Therefore Sprint 173:
- persists a canonical discovery metadata snapshot
- creates immutable SourceProvenance through KnowledgeIngestor
- evaluates provenance quality
- caps metadata-only evidence at LIMITED / SUPPORTING
- does not extract claims from metadata snapshots
- does not validate knowledge
- does not mutate strategies or place orders
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import argparse
import json
from pathlib import Path
import tempfile
from typing import Iterable, Mapping

from gaon.storage.foundation import GaonStorage

from .discovery import (
    DiscoveryProvider,
    DiscoveryResult,
    DiscoveryStatus,
)
from .execution import DiscoveryExecutionRun
from .ingestion import (
    IngestionResult,
    KnowledgeIngestor,
)
from .provenance import (
    SourceType,
    TrustLevel,
)
from .quality import (
    EvidenceGateStatus,
    EvidenceUse,
    SourceQualityAssessment,
    SourceQualityEvaluator,
)


DISCOVERY_INGESTION_SCHEMA_VERSION = 1
ARTIFACT_SCOPE = "discovery_metadata_only"


def canonical_discovery_snapshot(
    result: DiscoveryResult,
) -> bytes:
    """Return deterministic bytes representing only discovered metadata."""

    if result.status is not DiscoveryStatus.DISCOVERED:
        raise ValueError(
            "only DISCOVERED results can be persisted"
        )

    if not result.result_id.startswith(
        "discovery-result:"
    ):
        raise ValueError("invalid discovery result_id")

    if not result.query_id.startswith(
        "discovery-query:"
    ):
        raise ValueError("invalid discovery query_id")

    title = " ".join(result.title.strip().split())
    locator = result.locator.strip()

    if not title:
        raise ValueError("discovery title is required")

    if not locator.startswith("https://"):
        raise ValueError(
            "discovery locator must be HTTPS"
        )

    payload = {
        "schema_version":
            DISCOVERY_INGESTION_SCHEMA_VERSION,
        "artifact_scope": ARTIFACT_SCOPE,
        "discovery_result_id": result.result_id,
        "query_id": result.query_id,
        "provider": result.provider.value,
        "title": title,
        "locator": locator,
        "source_type": result.source_type.value,
        "discovery_status": result.status.value,
        "actual_source_body_fetched": False,
        "metadata_only": True,
        "external_content_policy":
            "untrusted-evidence-only",
        "executable": False,
        "eligible_for_claim_extraction": False,
        "knowledge_validated": False,
        "production_approved": False,
    }

    return (
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _metadata_quality_cap(
    assessment: SourceQualityAssessment,
) -> SourceQualityAssessment:
    """Metadata discovery can never become PRIMARY evidence by itself."""

    reasons = list(assessment.reasons)

    if "discovery_metadata_only" not in reasons:
        reasons.append(
            "discovery_metadata_only"
        )

    if (
        "source_body_not_fetched"
        not in reasons
    ):
        reasons.append(
            "source_body_not_fetched"
        )

    if (
        assessment.gate_status
        is EvidenceGateStatus.REJECTED
    ):
        return replace(
            assessment,
            reasons=tuple(reasons),
        )

    return SourceQualityAssessment(
        source_id=assessment.source_id,
        score=assessment.score,
        gate_status=EvidenceGateStatus.LIMITED,
        evidence_use=EvidenceUse.SUPPORTING,
        reasons=tuple(reasons),
        blockers=assessment.blockers,
        knowledge_validated=False,
        production_approved=False,
        external_content_policy=(
            "evidence-not-instruction"
        ),
    )


@dataclass(frozen=True)
class DiscoveryEvidenceRecord:
    discovery_result_id: str
    query_id: str
    provider: DiscoveryProvider
    source_type: SourceType
    source_id: str
    artifact_scope: str
    ingestion_status: str
    duplicate: bool
    byte_count: int
    raw_path: str
    metadata_path: str
    quality_score: int
    quality_status: EvidenceGateStatus
    evidence_use: EvidenceUse
    actual_source_body_fetched: bool = False
    metadata_only: bool = True
    eligible_for_claim_extraction: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version":
                DISCOVERY_INGESTION_SCHEMA_VERSION,
            "discovery_result_id":
                self.discovery_result_id,
            "query_id": self.query_id,
            "provider": self.provider.value,
            "source_type":
                self.source_type.value,
            "source_id": self.source_id,
            "artifact_scope":
                self.artifact_scope,
            "ingestion_status":
                self.ingestion_status,
            "duplicate": self.duplicate,
            "byte_count": self.byte_count,
            "raw_path": self.raw_path,
            "metadata_path": self.metadata_path,
            "quality_score": self.quality_score,
            "quality_status":
                self.quality_status.value,
            "evidence_use":
                self.evidence_use.value,
            "actual_source_body_fetched":
                self.actual_source_body_fetched,
            "metadata_only":
                self.metadata_only,
            "eligible_for_claim_extraction":
                self.eligible_for_claim_extraction,
            "knowledge_validated":
                self.knowledge_validated,
            "production_approved":
                self.production_approved,
            "strategy_mutated":
                self.strategy_mutated,
            "order_executed":
                self.order_executed,
        }


@dataclass(frozen=True)
class DiscoveryIngestionRun:
    run_id: str
    discovery_run_id: str
    records: tuple[
        DiscoveryEvidenceRecord, ...
    ]
    skipped_duplicates: int
    actual_source_bodies_fetched: int = 0
    claim_extraction_runs: int = 0
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version":
                DISCOVERY_INGESTION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "discovery_run_id":
                self.discovery_run_id,
            "records": [
                item.to_json()
                for item in self.records
            ],
            "skipped_duplicates":
                self.skipped_duplicates,
            "actual_source_bodies_fetched":
                self.actual_source_bodies_fetched,
            "claim_extraction_runs":
                self.claim_extraction_runs,
            "knowledge_validated":
                self.knowledge_validated,
            "production_approved":
                self.production_approved,
            "strategy_mutated":
                self.strategy_mutated,
            "order_executed":
                self.order_executed,
        }


class DiscoveryEvidenceIngestor:
    """Bridge discovered metadata into the existing evidence store."""

    def __init__(
        self,
        storage: GaonStorage | None = None,
        *,
        max_source_bytes: int | None = None,
    ) -> None:
        self.storage = (
            storage or GaonStorage()
        )

        self.ingestor = KnowledgeIngestor(
            self.storage,
            max_source_bytes=max_source_bytes,
        )

        self.quality = (
            SourceQualityEvaluator()
        )

    def ingest_result(
        self,
        result: DiscoveryResult,
    ) -> DiscoveryEvidenceRecord:
        self._validate_result_boundary(
            result
        )

        snapshot = (
            canonical_discovery_snapshot(
                result
            )
        )

        ingestion = (
            self.ingestor.ingest_bytes(
                snapshot,
                source_type=result.source_type,
                title=result.title,
                locator=result.locator,
                # Provider search proves discovery,
                # not source truth or source quality.
                trust_level=TrustLevel.UNKNOWN,
                notes=(
                    "artifact_scope="
                    f"{ARTIFACT_SCOPE}; "
                    f"provider={result.provider.value}; "
                    "source_body_fetched=false"
                ),
                suffix=".json",
            )
        )

        assessment = (
            self.quality.evaluate(
                ingestion.source
            )
        )

        assessment = (
            _metadata_quality_cap(
                assessment
            )
        )

        return self._record(
            result=result,
            ingestion=ingestion,
            assessment=assessment,
        )

    def ingest_results(
        self,
        results: Iterable[
            DiscoveryResult
        ],
        *,
        discovery_run_id: str,
    ) -> DiscoveryIngestionRun:
        if not discovery_run_id.startswith(
            "source-discovery-run:"
        ):
            raise ValueError(
                "invalid discovery_run_id"
            )

        unique: dict[
            str,
            DiscoveryResult,
        ] = {}

        duplicate_input_count = 0

        for result in results:
            existing = unique.get(
                result.result_id
            )

            if existing is None:
                unique[
                    result.result_id
                ] = result
                continue

            if existing != result:
                raise ValueError(
                    "same discovery result_id "
                    "has conflicting metadata"
                )

            duplicate_input_count += 1

        records = tuple(
            self.ingest_result(result)
            for _, result in sorted(
                unique.items()
            )
        )

        stored_duplicate_count = sum(
            1
            for record in records
            if record.duplicate
        )

        run_basis = {
            "discovery_run_id":
                discovery_run_id,
            "source_ids": sorted(
                record.source_id
                for record in records
            ),
        }

        import hashlib

        encoded = json.dumps(
            run_basis,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        run_id = (
            "discovery-ingestion-run:"
            + hashlib.sha256(
                encoded
            ).hexdigest()
        )

        return DiscoveryIngestionRun(
            run_id=run_id,
            discovery_run_id=
                discovery_run_id,
            records=records,
            skipped_duplicates=(
                duplicate_input_count
                + stored_duplicate_count
            ),
        )

    def ingest_execution(
        self,
        execution: DiscoveryExecutionRun,
    ) -> DiscoveryIngestionRun:
        if not execution.run_id.startswith(
            "source-discovery-run:"
        ):
            raise ValueError(
                "invalid discovery execution run"
            )

        # Only actual discovered metadata enters this bridge.
        return self.ingest_results(
            execution.results,
            discovery_run_id=
                execution.run_id,
        )

    @staticmethod
    def _validate_result_boundary(
        result: DiscoveryResult,
    ) -> None:
        if (
            result.status
            is not DiscoveryStatus.DISCOVERED
        ):
            raise ValueError(
                "only discovered results "
                "can enter evidence ingestion"
            )

        if result.provenance_created:
            raise ValueError(
                "unexpected pre-created provenance"
            )

        if result.ingested:
            raise ValueError(
                "unexpected pre-ingested result"
            )

        if result.quality_evaluated:
            raise ValueError(
                "unexpected pre-evaluated result"
            )

        if result.knowledge_validated:
            raise ValueError(
                "validated discovery result "
                "cannot enter this bridge"
            )

        if result.production_approved:
            raise ValueError(
                "production-approved discovery "
                "result cannot enter this bridge"
            )

    @staticmethod
    def _record(
        *,
        result: DiscoveryResult,
        ingestion: IngestionResult,
        assessment:
            SourceQualityAssessment,
    ) -> DiscoveryEvidenceRecord:
        return DiscoveryEvidenceRecord(
            discovery_result_id=
                result.result_id,
            query_id=result.query_id,
            provider=result.provider,
            source_type=
                result.source_type,
            source_id=
                ingestion.source.source_id,
            artifact_scope=ARTIFACT_SCOPE,
            ingestion_status=
                ingestion.status,
            duplicate=
                ingestion.duplicate,
            byte_count=
                ingestion.byte_count,
            raw_path=
                ingestion.raw_path,
            metadata_path=
                ingestion.metadata_path,
            quality_score=
                assessment.score,
            quality_status=
                assessment.gate_status,
            evidence_use=
                assessment.evidence_use,
        )


def discovery_ingestion_release_check(
    root: str | Path | None = None,
) -> Mapping[str, object]:
    storage = GaonStorage(root)

    bridge = DiscoveryEvidenceIngestor(
        storage,
        max_source_bytes=1024 * 1024,
    )

    paper = DiscoveryResult(
        result_id=(
            "discovery-result:paper"
        ),
        query_id=(
            "discovery-query:paper"
        ),
        provider=(
            DiscoveryProvider
            .ACADEMIC_SEARCH
        ),
        title=(
            "Trend Following Across "
            "Market Regimes"
        ),
        locator=(
            "https://doi.org/"
            "10.1000/test-paper"
        ),
        source_type=
            SourceType.ACADEMIC_PAPER,
        status=DiscoveryStatus.DISCOVERED,
    )

    dataset = DiscoveryResult(
        result_id=(
            "discovery-result:dataset"
        ),
        query_id=(
            "discovery-query:dataset"
        ),
        provider=(
            DiscoveryProvider
            .DATASET_CATALOG
        ),
        title="Market Regime Dataset",
        locator=(
            "https://doi.org/"
            "10.2000/test-dataset"
        ),
        source_type=SourceType.DATASET,
        status=DiscoveryStatus.DISCOVERED,
    )

    first = bridge.ingest_results(
        (paper, dataset),
        discovery_run_id=(
            "source-discovery-run:test"
        ),
    )

    second = bridge.ingest_results(
        (paper, dataset),
        discovery_run_id=(
            "source-discovery-run:test"
        ),
    )

    checks = {
        "records_created":
            len(first.records) == 2,
        "source_ids_created":
            all(
                item.source_id.startswith(
                    "source:"
                )
                for item in first.records
            ),
        "metadata_stored":
            all(
                Path(item.raw_path).is_file()
                and Path(
                    item.metadata_path
                ).is_file()
                for item in first.records
            ),
        "metadata_only":
            all(
                item.metadata_only
                and item.artifact_scope
                == ARTIFACT_SCOPE
                for item in first.records
            ),
        "body_not_fetched":
            all(
                not item.actual_source_body_fetched
                for item in first.records
            ),
        "claim_extraction_blocked":
            all(
                not item
                .eligible_for_claim_extraction
                for item in first.records
            ),
        "quality_capped":
            all(
                item.quality_status
                is EvidenceGateStatus.LIMITED
                and item.evidence_use
                is EvidenceUse.SUPPORTING
                for item in first.records
            ),
        "idempotent_storage":
            all(
                item.duplicate
                for item in second.records
            ),
        "not_validated":
            not first.knowledge_validated
            and all(
                not item.knowledge_validated
                for item in first.records
            ),
        "not_production":
            not first.production_approved
            and all(
                not item.production_approved
                for item in first.records
            ),
        "no_strategy_mutation":
            not first.strategy_mutated,
        "no_order":
            not first.order_executed,
    }

    if not all(checks.values()):
        failed = ",".join(
            name
            for name, ok in checks.items()
            if not ok
        )
        raise RuntimeError(
            "discovery ingestion release "
            f"check failed: {failed}"
        )

    return {
        "schema_version":
            DISCOVERY_INGESTION_SCHEMA_VERSION,
        "records": len(first.records),
        "duplicates":
            len(second.records),
        "quality_status":
            first.records[
                0
            ].quality_status.value,
        "artifact_scope":
            ARTIFACT_SCOPE,
        "checks": checks,
        "safety": "pass",
    }


def _main() -> int:
    parser = argparse.ArgumentParser(
        prog=(
            "python -m "
            "gaon.knowledge.discovery_ingestion"
        )
    )

    parser.add_argument(
        "command",
        choices=("release-check",),
    )

    parser.add_argument(
        "--root",
        default=None,
    )

    args = parser.parse_args()

    if args.root:
        payload = (
            discovery_ingestion_release_check(
                args.root
            )
        )
    else:
        with tempfile.TemporaryDirectory() as tmp:
            payload = (
                discovery_ingestion_release_check(
                    tmp
                )
            )

    print(
        "gaon-discovery-provenance-ingestion-release-check: PASS "
        f"schema_version={payload['schema_version']} "
        f"records={payload['records']} "
        f"duplicates={payload['duplicates']} "
        f"quality={payload['quality_status']} "
        f"artifact_scope={payload['artifact_scope']} "
        "source_body_fetched=false "
        "claim_extraction=false "
        "knowledge_validated=false "
        "production_approved=false "
        "strategy_mutated=false "
        "order_executed=false "
        "safety=pass"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
