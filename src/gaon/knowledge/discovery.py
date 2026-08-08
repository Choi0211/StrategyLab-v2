"""Sprint 171 — Source Discovery Foundation.

Transforms bounded research questions into safe source-discovery plans.

Sprint 171 does not perform network requests.

Safety invariants:
- discovery is derived from an existing ResearchQuestion
- only explicitly allowed source types may be requested
- search budgets are bounded
- duplicate queries are deterministic
- discovery results are not trusted knowledge
- results must still pass provenance, ingestion, quality, claim, and conflict gates
- no live trading / KIS / Broker order
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping

from .gaps import (
    KnowledgeGapType,
    ResearchPriority,
    ResearchQuestion,
)
from .provenance import SourceType


DISCOVERY_SCHEMA_VERSION = 1

_QUERY_SPACE_RE = re.compile(r"\s+")
_DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,63}$"
)


class DiscoveryStatus(str, Enum):
    PLANNED = "planned"
    DISCOVERED = "discovered"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


class DiscoveryProvider(str, Enum):
    ACADEMIC_SEARCH = "academic_search"
    OFFICIAL_WEB = "official_web"
    GENERAL_WEB = "general_web"
    DATASET_CATALOG = "dataset_catalog"


@dataclass(frozen=True)
class DiscoveryBudget:
    max_queries: int = 4
    max_results_per_query: int = 10
    max_total_results: int = 25

    def __post_init__(self) -> None:
        if self.max_queries <= 0:
            raise ValueError("max_queries must be positive")
        if self.max_results_per_query <= 0:
            raise ValueError("max_results_per_query must be positive")
        if self.max_total_results <= 0:
            raise ValueError("max_total_results must be positive")
        if (
            self.max_total_results
            > self.max_queries * self.max_results_per_query
        ):
            raise ValueError(
                "max_total_results exceeds query/result budget"
            )

    def to_json(self) -> dict[str, int]:
        return {
            "max_queries": self.max_queries,
            "max_results_per_query": self.max_results_per_query,
            "max_total_results": self.max_total_results,
        }


@dataclass(frozen=True)
class DiscoveryPolicy:
    allowed_source_types: tuple[SourceType, ...]
    allowed_providers: tuple[DiscoveryProvider, ...]
    blocked_domains: tuple[str, ...] = ()
    require_https: bool = True
    external_content_policy: str = "evidence-not-instruction"
    auto_ingest: bool = False
    auto_validate: bool = False

    def __post_init__(self) -> None:
        if not self.allowed_source_types:
            raise ValueError("at least one source type is required")
        if not self.allowed_providers:
            raise ValueError("at least one provider is required")

        for domain in self.blocked_domains:
            if not _DOMAIN_RE.fullmatch(domain):
                raise ValueError(f"invalid blocked domain: {domain}")

        if self.external_content_policy != "evidence-not-instruction":
            raise ValueError("unsafe external content policy")

        if self.auto_ingest:
            raise ValueError("Sprint 171 forbids auto_ingest")

        if self.auto_validate:
            raise ValueError("Sprint 171 forbids auto_validate")

    def to_json(self) -> dict[str, object]:
        return {
            "allowed_source_types": [
                item.value for item in self.allowed_source_types
            ],
            "allowed_providers": [
                item.value for item in self.allowed_providers
            ],
            "blocked_domains": list(self.blocked_domains),
            "require_https": self.require_https,
            "external_content_policy": self.external_content_policy,
            "auto_ingest": self.auto_ingest,
            "auto_validate": self.auto_validate,
        }


def normalize_query(value: str) -> str:
    normalized = _QUERY_SPACE_RE.sub(" ", value.strip())
    if not normalized:
        raise ValueError("query is required")
    if len(normalized) > 500:
        raise ValueError("query exceeds maximum length")
    return normalized


def canonical_query_id(
    *,
    question_id: str,
    provider: DiscoveryProvider,
    query: str,
) -> str:
    if not question_id.startswith("research-question:"):
        raise ValueError("invalid question_id")

    normalized = normalize_query(query)

    encoded = json.dumps(
        {
            "question_id": question_id,
            "provider": provider.value,
            "query": normalized.lower(),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return f"discovery-query:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class DiscoveryQuery:
    query_id: str
    question_id: str
    provider: DiscoveryProvider
    query: str
    source_types: tuple[SourceType, ...]
    sequence: int
    status: DiscoveryStatus = DiscoveryStatus.PLANNED

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if not self.source_types:
            raise ValueError("source_types cannot be empty")

    def to_json(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "question_id": self.question_id,
            "provider": self.provider.value,
            "query": self.query,
            "source_types": [
                item.value for item in self.source_types
            ],
            "sequence": self.sequence,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class SourceDiscoveryPlan:
    plan_id: str
    question_id: str
    topic_key: str
    gap_type: KnowledgeGapType
    priority: ResearchPriority
    queries: tuple[DiscoveryQuery, ...]
    budget: DiscoveryBudget
    policy: DiscoveryPolicy
    status: DiscoveryStatus = DiscoveryStatus.PLANNED
    network_executed: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    execution_authorized: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": DISCOVERY_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "question_id": self.question_id,
            "topic_key": self.topic_key,
            "gap_type": self.gap_type.value,
            "priority": self.priority.value,
            "queries": [
                item.to_json() for item in self.queries
            ],
            "budget": self.budget.to_json(),
            "policy": self.policy.to_json(),
            "status": self.status.value,
            "network_executed": self.network_executed,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "execution_authorized": self.execution_authorized,
        }


def canonical_plan_id(
    *,
    question_id: str,
    query_ids: Iterable[str],
) -> str:
    ids = sorted(set(query_ids))

    if not ids:
        raise ValueError("query_ids cannot be empty")

    encoded = json.dumps(
        {
            "question_id": question_id,
            "query_ids": ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return f"source-discovery-plan:{hashlib.sha256(encoded).hexdigest()}"


class SourceDiscoveryPlanner:
    """Creates deterministic, bounded discovery plans."""

    DEFAULT_POLICY = DiscoveryPolicy(
        allowed_source_types=(
            SourceType.ACADEMIC_PAPER,
            SourceType.OFFICIAL_DOCUMENT,
            SourceType.DATASET,
            SourceType.RESEARCH_REPORT,
        ),
        allowed_providers=(
            DiscoveryProvider.ACADEMIC_SEARCH,
            DiscoveryProvider.OFFICIAL_WEB,
            DiscoveryProvider.DATASET_CATALOG,
        ),
        blocked_domains=(),
        require_https=True,
        auto_ingest=False,
        auto_validate=False,
    )

    def __init__(
        self,
        *,
        budget: DiscoveryBudget | None = None,
        policy: DiscoveryPolicy | None = None,
    ) -> None:
        self.budget = budget or DiscoveryBudget()
        self.policy = policy or self.DEFAULT_POLICY

    def build(
        self,
        question: ResearchQuestion,
    ) -> SourceDiscoveryPlan:
        raw_queries = self._query_templates(question)

        unique: dict[str, tuple[DiscoveryProvider, str, tuple[SourceType, ...]]] = {}

        for provider, query, source_types in raw_queries:
            if provider not in self.policy.allowed_providers:
                continue

            permitted_types = tuple(
                item
                for item in source_types
                if item in self.policy.allowed_source_types
            )

            if not permitted_types:
                continue

            query_id = canonical_query_id(
                question_id=question.question_id,
                provider=provider,
                query=query,
            )

            unique.setdefault(
                query_id,
                (
                    provider,
                    normalize_query(query),
                    permitted_types,
                ),
            )

        ordered_items = list(unique.items())

        if not ordered_items:
            raise ValueError(
                "no discovery query survives policy filtering"
            )

        ordered_items = ordered_items[: self.budget.max_queries]

        queries = tuple(
            DiscoveryQuery(
                query_id=query_id,
                question_id=question.question_id,
                provider=provider,
                query=query,
                source_types=source_types,
                sequence=index,
            )
            for index, (
                query_id,
                (provider, query, source_types),
            ) in enumerate(ordered_items)
        )

        return SourceDiscoveryPlan(
            plan_id=canonical_plan_id(
                question_id=question.question_id,
                query_ids=(
                    item.query_id
                    for item in queries
                ),
            ),
            question_id=question.question_id,
            topic_key=question.topic_key,
            gap_type=question.gap_type,
            priority=question.priority,
            queries=queries,
            budget=self.budget,
            policy=self.policy,
        )

    def _query_templates(
        self,
        question: ResearchQuestion,
    ) -> tuple[
        tuple[
            DiscoveryProvider,
            str,
            tuple[SourceType, ...],
        ],
        ...
    ]:
        topic = question.topic_key.replace(".", " ").replace(":", " ")

        if question.gap_type is KnowledgeGapType.CONTRADICTION:
            return (
                (
                    DiscoveryProvider.ACADEMIC_SEARCH,
                    f"{topic} contradictory evidence market regimes",
                    (
                        SourceType.ACADEMIC_PAPER,
                        SourceType.RESEARCH_REPORT,
                    ),
                ),
                (
                    DiscoveryProvider.OFFICIAL_WEB,
                    f"{topic} official research methodology",
                    (
                        SourceType.OFFICIAL_DOCUMENT,
                    ),
                ),
                (
                    DiscoveryProvider.DATASET_CATALOG,
                    f"{topic} dataset market regime",
                    (
                        SourceType.DATASET,
                    ),
                ),
            )

        if (
            question.gap_type
            is KnowledgeGapType.INSUFFICIENT_INDEPENDENCE
        ):
            return (
                (
                    DiscoveryProvider.ACADEMIC_SEARCH,
                    f"{topic} independent replication evidence",
                    (
                        SourceType.ACADEMIC_PAPER,
                        SourceType.RESEARCH_REPORT,
                    ),
                ),
                (
                    DiscoveryProvider.OFFICIAL_WEB,
                    f"{topic} official evidence",
                    (
                        SourceType.OFFICIAL_DOCUMENT,
                    ),
                ),
            )

        if (
            question.gap_type
            is KnowledgeGapType.MISSING_DIRECTIONAL_EVIDENCE
        ):
            return (
                (
                    DiscoveryProvider.ACADEMIC_SEARCH,
                    f"{topic} empirical evidence",
                    (
                        SourceType.ACADEMIC_PAPER,
                        SourceType.RESEARCH_REPORT,
                    ),
                ),
                (
                    DiscoveryProvider.DATASET_CATALOG,
                    f"{topic} dataset",
                    (
                        SourceType.DATASET,
                    ),
                ),
            )

        raise ValueError(
            f"unsupported gap type: {question.gap_type}"
        )


@dataclass(frozen=True)
class DiscoveryResult:
    result_id: str
    query_id: str
    provider: DiscoveryProvider
    title: str
    locator: str
    source_type: SourceType
    status: DiscoveryStatus
    provenance_created: bool = False
    ingested: bool = False
    quality_evaluated: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": DISCOVERY_SCHEMA_VERSION,
            "result_id": self.result_id,
            "query_id": self.query_id,
            "provider": self.provider.value,
            "title": self.title,
            "locator": self.locator,
            "source_type": self.source_type.value,
            "status": self.status.value,
            "provenance_created": self.provenance_created,
            "ingested": self.ingested,
            "quality_evaluated": self.quality_evaluated,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
        }


def discovery_release_check() -> Mapping[str, object]:
    from .conflicts import ConflictStatus
    from .gaps import (
        KnowledgeGapType,
        RequiredEvidence,
        RequiredEvidenceType,
        ResearchQuestion,
        ResearchStopCondition,
    )

    question = ResearchQuestion(
        question_id="research-question:test",
        topic_key="trend.regime.robustness",
        gap_type=KnowledgeGapType.CONTRADICTION,
        question=(
            "What independent evidence can explain the conflict?"
        ),
        priority=ResearchPriority.HIGH,
        required_evidence=(
            RequiredEvidence(
                evidence_type=
                    RequiredEvidenceType.INDEPENDENT_PRIMARY_SOURCE,
                minimum_independent_sources=2,
                rationale="test",
            ),
        ),
        stop_conditions=(
            ResearchStopCondition.OPPOSING_EVIDENCE_RESOLVED,
        ),
        parent_conflict_id="knowledge-conflict:test",
        source_state=ConflictStatus.UNRESOLVED_CONFLICT,
    )

    plan = SourceDiscoveryPlanner().build(question)

    checks = {
        "plan_created": bool(plan.plan_id),
        "queries_bounded":
            1 <= len(plan.queries) <= plan.budget.max_queries,
        "all_queries_unique":
            len({item.query_id for item in plan.queries})
            == len(plan.queries),
        "allowed_providers_only":
            all(
                item.provider
                in plan.policy.allowed_providers
                for item in plan.queries
            ),
        "allowed_source_types_only":
            all(
                all(
                    source_type
                    in plan.policy.allowed_source_types
                    for source_type in item.source_types
                )
                for item in plan.queries
            ),
        "network_not_executed":
            plan.network_executed is False,
        "auto_ingest_disabled":
            plan.policy.auto_ingest is False,
        "auto_validate_disabled":
            plan.policy.auto_validate is False,
        "not_validated":
            plan.knowledge_validated is False,
        "not_production":
            plan.production_approved is False,
        "execution_not_authorized":
            plan.execution_authorized is False,
    }

    if not all(checks.values()):
        failed = ",".join(
            key for key, value in checks.items()
            if not value
        )
        raise RuntimeError(
            f"source discovery release check failed: {failed}"
        )

    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "queries": len(plan.queries),
        "max_queries": plan.budget.max_queries,
        "max_total_results": plan.budget.max_total_results,
        "providers": len(plan.policy.allowed_providers),
        "checks": checks,
        "safety": "pass",
    }


if __name__ == "__main__":
    payload = discovery_release_check()

    print(
        "gaon-source-discovery-release-check: PASS "
        f"schema_version={payload['schema_version']} "
        f"queries={payload['queries']} "
        f"max_queries={payload['max_queries']} "
        f"max_total_results={payload['max_total_results']} "
        f"providers={payload['providers']} "
        "network_executed=false "
        "auto_ingest=false "
        "auto_validate=false "
        "knowledge_validated=false "
        "production_approved=false "
        "execution_authorized=false "
        "safety=pass"
    )
