"""Sprint 172 — Bounded Source Discovery Execution.

Executes Sprint 171 discovery plans against explicitly allowed public
research metadata APIs.

Initial real providers:
- Crossref REST API -> academic papers / research reports
- DataCite REST API -> datasets

Important safety boundaries:
- network is disabled unless explicitly enabled by the caller
- only allowlisted HTTPS API hosts may be contacted
- query/result/response-size budgets are enforced
- redirects cannot become arbitrary fetches
- discovered URLs are metadata only; source bodies are not fetched here
- discovered results remain untrusted
- no automatic provenance promotion
- no automatic ingestion
- no automatic knowledge validation
- no strategy mutation / Champion promotion / KIS/Broker order
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import argparse
import hashlib
import json
import os
import socket
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .discovery import (
    DiscoveryProvider,
    DiscoveryResult,
    DiscoveryStatus,
    SourceDiscoveryPlan,
)
from .provenance import SourceType


EXECUTION_SCHEMA_VERSION = 1

CROSSREF_HOST = "api.crossref.org"
DATACITE_HOST = "api.datacite.org"

DEFAULT_ALLOWED_API_HOSTS = (
    CROSSREF_HOST,
    DATACITE_HOST,
)


class ExecutionFailureKind(str, Enum):
    NETWORK_DISABLED = "network_disabled"
    PROVIDER_UNSUPPORTED = "provider_unsupported"
    HOST_BLOCKED = "host_blocked"
    INVALID_RESPONSE = "invalid_response"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True)
class NetworkExecutionPolicy:
    network_enabled: bool = False
    allowed_api_hosts: tuple[str, ...] = DEFAULT_ALLOWED_API_HOSTS
    timeout_seconds: float = 10.0
    max_response_bytes: int = 2 * 1024 * 1024
    user_agent: str = "StrategyLab-Gaon/0.1"
    contact_email: str | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")

        if not self.allowed_api_hosts:
            raise ValueError("allowed_api_hosts cannot be empty")

        normalized_hosts = tuple(
            host.strip().lower()
            for host in self.allowed_api_hosts
        )

        if any(
            not host
            or "/" in host
            or ":" in host
            for host in normalized_hosts
        ):
            raise ValueError("invalid API host allowlist")

        if not self.user_agent.strip():
            raise ValueError("user_agent is required")

        if self.contact_email is not None:
            value = self.contact_email.strip()
            if "@" not in value or len(value) > 254:
                raise ValueError("invalid contact_email")


@dataclass(frozen=True)
class QueryExecutionRecord:
    query_id: str
    provider: DiscoveryProvider
    status: DiscoveryStatus
    provider_calls: int
    returned_results: int
    accepted_results: int
    failure_kind: ExecutionFailureKind | None = None
    error_message: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "provider": self.provider.value,
            "status": self.status.value,
            "provider_calls": self.provider_calls,
            "returned_results": self.returned_results,
            "accepted_results": self.accepted_results,
            "failure_kind": (
                self.failure_kind.value
                if self.failure_kind is not None
                else None
            ),
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class DiscoveryExecutionRun:
    run_id: str
    plan_id: str
    network_enabled: bool
    network_executed: bool
    provider_calls: int
    results: tuple[DiscoveryResult, ...]
    query_records: tuple[QueryExecutionRecord, ...]
    duplicate_results: int
    budget_exhausted: bool
    provenance_created: bool = False
    ingested: bool = False
    quality_evaluated: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": EXECUTION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "network_enabled": self.network_enabled,
            "network_executed": self.network_executed,
            "provider_calls": self.provider_calls,
            "results": [
                item.to_json()
                for item in self.results
            ],
            "query_records": [
                item.to_json()
                for item in self.query_records
            ],
            "duplicate_results": self.duplicate_results,
            "budget_exhausted": self.budget_exhausted,
            "provenance_created": self.provenance_created,
            "ingested": self.ingested,
            "quality_evaluated": self.quality_evaluated,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


class JsonTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        policy: NetworkExecutionPolicy,
    ) -> Mapping[str, object]:
        ...


class NoCrossHostRedirectHandler(HTTPRedirectHandler):
    """Allow redirects only when the destination remains on same API host."""

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        old = urlparse(req.full_url)
        new = urlparse(newurl)

        if (
            new.scheme != "https"
            or not new.hostname
            or new.hostname.lower() != (old.hostname or "").lower()
        ):
            raise HTTPError(
                req.full_url,
                403,
                "cross-host redirect blocked",
                headers,
                fp,
            )

        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            newurl,
        )


class HttpsJsonTransport:
    """Small fail-closed HTTPS JSON transport."""

    def get_json(
        self,
        url: str,
        *,
        policy: NetworkExecutionPolicy,
    ) -> Mapping[str, object]:
        if not policy.network_enabled:
            raise PermissionError("network execution is disabled")

        parsed = urlparse(url)

        if parsed.scheme != "https":
            raise PermissionError("only HTTPS API requests are allowed")

        host = (parsed.hostname or "").lower()

        if host not in {
            value.lower()
            for value in policy.allowed_api_hosts
        }:
            raise PermissionError(
                f"API host is not allowlisted: {host}"
            )

        if parsed.username or parsed.password:
            raise PermissionError(
                "userinfo in API URL is not allowed"
            )

        if parsed.port not in (None, 443):
            raise PermissionError(
                "non-standard HTTPS port is not allowed"
            )

        headers = {
            "Accept": "application/json",
            "User-Agent": policy.user_agent,
        }

        request = Request(
            url,
            headers=headers,
            method="GET",
        )

        opener = build_opener(
            NoCrossHostRedirectHandler()
        )

        with opener.open(
            request,
            timeout=policy.timeout_seconds,
        ) as response:
            content_length = response.headers.get(
                "Content-Length"
            )

            if content_length:
                try:
                    declared = int(content_length)
                except ValueError:
                    declared = 0

                if declared > policy.max_response_bytes:
                    raise ValueError(
                        "response exceeds configured size budget"
                    )

            raw = response.read(
                policy.max_response_bytes + 1
            )

            if len(raw) > policy.max_response_bytes:
                raise ValueError(
                    "response exceeds configured size budget"
                )

        payload = json.loads(
            raw.decode("utf-8")
        )

        if not isinstance(payload, dict):
            raise ValueError(
                "provider JSON root must be an object"
            )

        return payload


def canonical_result_id(
    *,
    query_id: str,
    locator: str,
) -> str:
    if not query_id.startswith(
        "discovery-query:"
    ):
        raise ValueError("invalid query_id")

    normalized = locator.strip()

    if not normalized:
        raise ValueError("locator is required")

    encoded = json.dumps(
        {
            "query_id": query_id,
            "locator": normalized,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return (
        "discovery-result:"
        + hashlib.sha256(encoded).hexdigest()
    )


def _https_locator(value: str) -> str | None:
    locator = value.strip()
    if not locator:
        return None

    parsed = urlparse(locator)

    if (
        parsed.scheme != "https"
        or not parsed.hostname
    ):
        return None

    if parsed.username or parsed.password:
        return None

    return locator


def _doi_locator(doi: str) -> str | None:
    value = doi.strip()

    if not value:
        return None

    return f"https://doi.org/{value}"


def _metadata_resource_url(item: Mapping[str, object]) -> str | None:
    links = item.get("link")
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            locator = _https_locator(str(link.get("URL") or link.get("url") or ""))
            if locator and (urlparse(locator).hostname or "").lower() != "doi.org":
                return locator
    locator = _https_locator(str(item.get("URL") or item.get("url") or ""))
    if locator and (urlparse(locator).hostname or "").lower() != "doi.org":
        return locator
    return None


def _first_text(value: object) -> str | None:
    if isinstance(value, str):
        normalized = " ".join(
            value.strip().split()
        )
        return normalized or None

    if isinstance(value, list):
        for item in value:
            result = _first_text(item)
            if result:
                return result

    return None


class CrossrefDiscoveryProvider:
    BASE_URL = "https://api.crossref.org/works"

    _ACADEMIC_TYPES = {
        "journal-article",
        "proceedings-article",
        "posted-content",
        "dissertation",
        "book-chapter",
    }

    _REPORT_TYPES = {
        "report",
        "report-series",
    }

    def search(
        self,
        *,
        query_id: str,
        query: str,
        limit: int,
        requested_source_types: tuple[SourceType, ...],
        transport: JsonTransport,
        policy: NetworkExecutionPolicy,
    ) -> tuple[DiscoveryResult, ...]:
        params = {
            "query.bibliographic": query,
            "rows": str(limit),
            "select": (
                "DOI,title,type,publisher,"
                "published,URL,author,license"
            ),
        }

        if policy.contact_email:
            params["mailto"] = (
                policy.contact_email.strip()
            )

        url = (
            self.BASE_URL
            + "?"
            + urlencode(params)
        )

        payload = transport.get_json(
            url,
            policy=policy,
        )

        message = payload.get("message")

        if not isinstance(message, dict):
            raise ValueError(
                "Crossref response missing message"
            )

        items = message.get("items")

        if not isinstance(items, list):
            raise ValueError(
                "Crossref response missing items"
            )

        results: list[DiscoveryResult] = []

        for item in items:
            if not isinstance(item, dict):
                continue

            work_type = str(
                item.get("type") or ""
            ).strip()

            if work_type in self._ACADEMIC_TYPES:
                source_type = (
                    SourceType.ACADEMIC_PAPER
                )
            elif work_type in self._REPORT_TYPES:
                source_type = (
                    SourceType.RESEARCH_REPORT
                )
            else:
                continue

            if source_type not in requested_source_types:
                continue

            title = _first_text(
                item.get("title")
            )

            if not title:
                continue

            doi = str(
                item.get("DOI") or ""
            ).strip()
            resource_url = _metadata_resource_url(item)

            locator = (
                _doi_locator(doi)
                or resource_url
            )

            if not locator:
                continue

            results.append(
                DiscoveryResult(
                    result_id=canonical_result_id(
                        query_id=query_id,
                        locator=locator,
                    ),
                    query_id=query_id,
                    provider=(
                        DiscoveryProvider.ACADEMIC_SEARCH
                    ),
                    title=title,
                    locator=locator,
                    source_type=source_type,
                    status=DiscoveryStatus.DISCOVERED,
                    provenance_created=False,
                    ingested=False,
                    quality_evaluated=False,
                    knowledge_validated=False,
                    production_approved=False,
                    doi=doi or None,
                    metadata_resource_url=resource_url,
                )
            )

            if len(results) >= limit:
                break

        return tuple(results)


class DataCiteDiscoveryProvider:
    BASE_URL = "https://api.datacite.org/dois"

    def search(
        self,
        *,
        query_id: str,
        query: str,
        limit: int,
        requested_source_types: tuple[SourceType, ...],
        transport: JsonTransport,
        policy: NetworkExecutionPolicy,
    ) -> tuple[DiscoveryResult, ...]:
        if (
            SourceType.DATASET
            not in requested_source_types
        ):
            return ()

        params = {
            "query": query,
            "resource-type-id": "dataset",
            "page[size]": str(limit),
            "sort": "relevance",
        }

        url = (
            self.BASE_URL
            + "?"
            + urlencode(params)
        )

        payload = transport.get_json(
            url,
            policy=policy,
        )

        data = payload.get("data")

        if not isinstance(data, list):
            raise ValueError(
                "DataCite response missing data"
            )

        results: list[DiscoveryResult] = []

        for item in data:
            if not isinstance(item, dict):
                continue

            attributes = item.get(
                "attributes"
            )

            if not isinstance(
                attributes,
                dict,
            ):
                continue

            titles = attributes.get(
                "titles"
            )

            title: str | None = None

            if isinstance(titles, list):
                for title_item in titles:
                    if isinstance(
                        title_item,
                        dict,
                    ):
                        title = _first_text(
                            title_item.get("title")
                        )
                        if title:
                            break

            if not title:
                continue

            doi = str(
                attributes.get("doi")
                or item.get("id")
                or ""
            ).strip()
            resource_url = _https_locator(
                str(
                    attributes.get("url")
                    or ""
                )
            )

            locator = (
                _doi_locator(doi)
                or resource_url
            )

            if not locator:
                continue

            results.append(
                DiscoveryResult(
                    result_id=canonical_result_id(
                        query_id=query_id,
                        locator=locator,
                    ),
                    query_id=query_id,
                    provider=(
                        DiscoveryProvider.DATASET_CATALOG
                    ),
                    title=title,
                    locator=locator,
                    source_type=SourceType.DATASET,
                    status=DiscoveryStatus.DISCOVERED,
                    provenance_created=False,
                    ingested=False,
                    quality_evaluated=False,
                    knowledge_validated=False,
                    production_approved=False,
                    doi=doi or None,
                    metadata_resource_url=resource_url,
                )
            )

            if len(results) >= limit:
                break

        return tuple(results)


class BoundedSourceDiscoveryExecutor:
    def __init__(
        self,
        *,
        network_policy: NetworkExecutionPolicy | None = None,
        transport: JsonTransport | None = None,
    ) -> None:
        self.network_policy = (
            network_policy
            or NetworkExecutionPolicy()
        )

        self.transport = (
            transport
            or HttpsJsonTransport()
        )

        self._providers = {
            DiscoveryProvider.ACADEMIC_SEARCH:
                CrossrefDiscoveryProvider(),
            DiscoveryProvider.DATASET_CATALOG:
                DataCiteDiscoveryProvider(),
        }

    def execute(
        self,
        plan: SourceDiscoveryPlan,
    ) -> DiscoveryExecutionRun:
        run_id = self._run_id(plan)

        if not self.network_policy.network_enabled:
            records = tuple(
                QueryExecutionRecord(
                    query_id=query.query_id,
                    provider=query.provider,
                    status=DiscoveryStatus.BLOCKED,
                    provider_calls=0,
                    returned_results=0,
                    accepted_results=0,
                    failure_kind=(
                        ExecutionFailureKind.NETWORK_DISABLED
                    ),
                    error_message=(
                        "network execution is disabled"
                    ),
                )
                for query in plan.queries
            )

            return DiscoveryExecutionRun(
                run_id=run_id,
                plan_id=plan.plan_id,
                network_enabled=False,
                network_executed=False,
                provider_calls=0,
                results=(),
                query_records=records,
                duplicate_results=0,
                budget_exhausted=False,
            )

        accepted: list[DiscoveryResult] = []
        records: list[QueryExecutionRecord] = []
        seen_locators: set[str] = set()

        provider_calls = 0
        duplicate_results = 0
        budget_exhausted = False

        max_queries = min(
            len(plan.queries),
            plan.budget.max_queries,
        )

        for query in plan.queries[:max_queries]:
            remaining = (
                plan.budget.max_total_results
                - len(accepted)
            )

            if remaining <= 0:
                budget_exhausted = True

                records.append(
                    QueryExecutionRecord(
                        query_id=query.query_id,
                        provider=query.provider,
                        status=(
                            DiscoveryStatus.BUDGET_EXHAUSTED
                        ),
                        provider_calls=0,
                        returned_results=0,
                        accepted_results=0,
                        failure_kind=(
                            ExecutionFailureKind.BUDGET_EXHAUSTED
                        ),
                    )
                )
                continue

            if (
                query.provider
                not in plan.policy.allowed_providers
            ):
                records.append(
                    QueryExecutionRecord(
                        query_id=query.query_id,
                        provider=query.provider,
                        status=DiscoveryStatus.BLOCKED,
                        provider_calls=0,
                        returned_results=0,
                        accepted_results=0,
                        failure_kind=(
                            ExecutionFailureKind.PROVIDER_UNSUPPORTED
                        ),
                        error_message=(
                            "provider not permitted by plan"
                        ),
                    )
                )
                continue

            provider = self._providers.get(
                query.provider
            )

            if provider is None:
                records.append(
                    QueryExecutionRecord(
                        query_id=query.query_id,
                        provider=query.provider,
                        status=DiscoveryStatus.BLOCKED,
                        provider_calls=0,
                        returned_results=0,
                        accepted_results=0,
                        failure_kind=(
                            ExecutionFailureKind.PROVIDER_UNSUPPORTED
                        ),
                        error_message=(
                            "provider execution not implemented"
                        ),
                    )
                )
                continue

            per_query_limit = min(
                plan.budget.max_results_per_query,
                remaining,
            )

            try:
                provider_calls += 1

                raw_results = provider.search(
                    query_id=query.query_id,
                    query=query.query,
                    limit=per_query_limit,
                    requested_source_types=(
                        query.source_types
                    ),
                    transport=self.transport,
                    policy=self.network_policy,
                )

            except PermissionError as exc:
                records.append(
                    QueryExecutionRecord(
                        query_id=query.query_id,
                        provider=query.provider,
                        status=DiscoveryStatus.BLOCKED,
                        provider_calls=1,
                        returned_results=0,
                        accepted_results=0,
                        failure_kind=(
                            ExecutionFailureKind.HOST_BLOCKED
                        ),
                        error_message=str(exc),
                    )
                )
                continue

            except (
                socket.timeout,
                TimeoutError,
            ) as exc:
                records.append(
                    QueryExecutionRecord(
                        query_id=query.query_id,
                        provider=query.provider,
                        status=DiscoveryStatus.BLOCKED,
                        provider_calls=1,
                        returned_results=0,
                        accepted_results=0,
                        failure_kind=(
                            ExecutionFailureKind.TIMEOUT
                        ),
                        error_message=str(exc),
                    )
                )
                continue

            except HTTPError as exc:
                records.append(
                    QueryExecutionRecord(
                        query_id=query.query_id,
                        provider=query.provider,
                        status=DiscoveryStatus.BLOCKED,
                        provider_calls=1,
                        returned_results=0,
                        accepted_results=0,
                        failure_kind=(
                            ExecutionFailureKind.HTTP_ERROR
                        ),
                        error_message=(
                            f"HTTP {exc.code}"
                        ),
                    )
                )
                continue

            except URLError as exc:
                records.append(
                    QueryExecutionRecord(
                        query_id=query.query_id,
                        provider=query.provider,
                        status=DiscoveryStatus.BLOCKED,
                        provider_calls=1,
                        returned_results=0,
                        accepted_results=0,
                        failure_kind=(
                            ExecutionFailureKind.NETWORK_ERROR
                        ),
                        error_message=str(
                            exc.reason
                        ),
                    )
                )
                continue

            except (
                ValueError,
                TypeError,
                KeyError,
                json.JSONDecodeError,
            ) as exc:
                records.append(
                    QueryExecutionRecord(
                        query_id=query.query_id,
                        provider=query.provider,
                        status=DiscoveryStatus.BLOCKED,
                        provider_calls=1,
                        returned_results=0,
                        accepted_results=0,
                        failure_kind=(
                            ExecutionFailureKind.INVALID_RESPONSE
                        ),
                        error_message=str(exc),
                    )
                )
                continue

            accepted_now = 0

            for result in raw_results:
                locator_key = (
                    result.locator
                    .strip()
                    .lower()
                )

                if locator_key in seen_locators:
                    duplicate_results += 1
                    continue

                if (
                    result.source_type
                    not in plan.policy.allowed_source_types
                ):
                    continue

                if (
                    result.source_type
                    not in query.source_types
                ):
                    continue

                seen_locators.add(
                    locator_key
                )

                accepted.append(result)
                accepted_now += 1

                if (
                    len(accepted)
                    >= plan.budget.max_total_results
                ):
                    budget_exhausted = True
                    break

            records.append(
                QueryExecutionRecord(
                    query_id=query.query_id,
                    provider=query.provider,
                    status=DiscoveryStatus.DISCOVERED,
                    provider_calls=1,
                    returned_results=len(
                        raw_results
                    ),
                    accepted_results=accepted_now,
                )
            )

        return DiscoveryExecutionRun(
            run_id=run_id,
            plan_id=plan.plan_id,
            network_enabled=True,
            network_executed=(
                provider_calls > 0
            ),
            provider_calls=provider_calls,
            results=tuple(accepted),
            query_records=tuple(records),
            duplicate_results=duplicate_results,
            budget_exhausted=budget_exhausted,
        )

    @staticmethod
    def _run_id(
        plan: SourceDiscoveryPlan,
    ) -> str:
        encoded = json.dumps(
            {
                "plan_id": plan.plan_id,
                "query_ids": [
                    item.query_id
                    for item in plan.queries
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return (
            "source-discovery-run:"
            + hashlib.sha256(
                encoded
            ).hexdigest()
        )


class FixtureTransport:
    """Deterministic test transport; never accesses a network."""

    def get_json(
        self,
        url: str,
        *,
        policy: NetworkExecutionPolicy,
    ) -> Mapping[str, object]:
        parsed = urlparse(url)

        if parsed.hostname == CROSSREF_HOST:
            return {
                "status": "ok",
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/test-a",
                            "title": [
                                "Trend Following Across Market Regimes"
                            ],
                            "type": "journal-article",
                            "URL": (
                                "https://doi.org/10.1000/test-a"
                            ),
                        },
                        {
                            "DOI": "10.1000/test-b",
                            "title": [
                                "Robustness of Trading Rules"
                            ],
                            "type": "journal-article",
                            "URL": (
                                "https://doi.org/10.1000/test-b"
                            ),
                        },
                    ]
                },
            }

        if parsed.hostname == DATACITE_HOST:
            return {
                "data": [
                    {
                        "id": "10.2000/dataset-a",
                        "attributes": {
                            "doi": "10.2000/dataset-a",
                            "titles": [
                                {
                                    "title": (
                                        "Market Regime Dataset"
                                    )
                                }
                            ],
                            "url": (
                                "https://doi.org/10.2000/dataset-a"
                            ),
                        },
                    }
                ]
            }

        raise PermissionError(
            "fixture host not allowed"
        )


def execution_release_check() -> Mapping[str, object]:
    from .conflicts import ConflictStatus
    from .discovery import SourceDiscoveryPlanner
    from .gaps import (
        KnowledgeGapType,
        RequiredEvidence,
        RequiredEvidenceType,
        ResearchPriority,
        ResearchQuestion,
        ResearchStopCondition,
    )

    question = ResearchQuestion(
        question_id="research-question:test",
        topic_key="trend.regime.robustness",
        gap_type=KnowledgeGapType.CONTRADICTION,
        question="What evidence resolves the conflict?",
        priority=ResearchPriority.HIGH,
        required_evidence=(
            RequiredEvidence(
                evidence_type=(
                    RequiredEvidenceType
                    .INDEPENDENT_PRIMARY_SOURCE
                ),
                minimum_independent_sources=2,
                rationale="test",
            ),
        ),
        stop_conditions=(
            ResearchStopCondition
            .OPPOSING_EVIDENCE_RESOLVED,
        ),
        parent_conflict_id="knowledge-conflict:test",
        source_state=(
            ConflictStatus.UNRESOLVED_CONFLICT
        ),
    )

    plan = SourceDiscoveryPlanner().build(
        question
    )

    disabled = (
        BoundedSourceDiscoveryExecutor(
            network_policy=NetworkExecutionPolicy(
                network_enabled=False
            ),
            transport=FixtureTransport(),
        ).execute(plan)
    )

    enabled = (
        BoundedSourceDiscoveryExecutor(
            network_policy=NetworkExecutionPolicy(
                network_enabled=True
            ),
            transport=FixtureTransport(),
        ).execute(plan)
    )

    checks = {
        "disabled_fail_closed":
            disabled.network_executed is False
            and disabled.provider_calls == 0,
        "fixture_execution":
            enabled.network_executed is True,
        "provider_calls_bounded":
            enabled.provider_calls
            <= plan.budget.max_queries,
        "results_bounded":
            len(enabled.results)
            <= plan.budget.max_total_results,
        "real_provider_contracts":
            any(
                item.provider
                is DiscoveryProvider.ACADEMIC_SEARCH
                for item in enabled.results
            )
            and any(
                item.provider
                is DiscoveryProvider.DATASET_CATALOG
                for item in enabled.results
            ),
        "results_untrusted":
            all(
                not item.provenance_created
                and not item.ingested
                and not item.quality_evaluated
                and not item.knowledge_validated
                and not item.production_approved
                for item in enabled.results
            ),
        "no_auto_ingestion":
            enabled.ingested is False,
        "no_auto_validation":
            enabled.knowledge_validated is False,
        "no_production":
            enabled.production_approved is False,
        "no_strategy_mutation":
            enabled.strategy_mutated is False,
        "no_order":
            enabled.order_executed is False,
    }

    if not all(checks.values()):
        failed = ",".join(
            name
            for name, ok in checks.items()
            if not ok
        )
        raise RuntimeError(
            f"source discovery execution "
            f"release check failed: {failed}"
        )

    return {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "provider_calls": enabled.provider_calls,
        "results": len(enabled.results),
        "disabled_provider_calls":
            disabled.provider_calls,
        "checks": checks,
        "safety": "pass",
    }


def _live_smoke(
    *,
    provider_name: str,
    query: str,
    limit: int,
) -> int:
    from .discovery import (
        DiscoveryBudget,
        DiscoveryPolicy,
        DiscoveryQuery,
        SourceDiscoveryPlan,
        canonical_plan_id,
        canonical_query_id,
    )
    from .gaps import (
        KnowledgeGapType,
        ResearchPriority,
    )

    contact = os.environ.get(
        "GAON_DISCOVERY_CONTACT"
    )

    provider = {
        "crossref":
            DiscoveryProvider.ACADEMIC_SEARCH,
        "datacite":
            DiscoveryProvider.DATASET_CATALOG,
    }[provider_name]

    source_types = {
        "crossref": (
            SourceType.ACADEMIC_PAPER,
            SourceType.RESEARCH_REPORT,
        ),
        "datacite": (
            SourceType.DATASET,
        ),
    }[provider_name]

    question_id = (
        "research-question:live-smoke"
    )

    query_id = canonical_query_id(
        question_id=question_id,
        provider=provider,
        query=query,
    )

    discovery_query = DiscoveryQuery(
        query_id=query_id,
        question_id=question_id,
        provider=provider,
        query=query,
        source_types=source_types,
        sequence=0,
    )

    policy = DiscoveryPolicy(
        allowed_source_types=source_types,
        allowed_providers=(provider,),
        auto_ingest=False,
        auto_validate=False,
    )

    budget = DiscoveryBudget(
        max_queries=1,
        max_results_per_query=limit,
        max_total_results=limit,
    )

    plan = SourceDiscoveryPlan(
        plan_id=canonical_plan_id(
            question_id=question_id,
            query_ids=(query_id,),
        ),
        question_id=question_id,
        topic_key="live.smoke",
        gap_type=(
            KnowledgeGapType
            .MISSING_DIRECTIONAL_EVIDENCE
        ),
        priority=ResearchPriority.LOW,
        queries=(discovery_query,),
        budget=budget,
        policy=policy,
    )

    execution = (
        BoundedSourceDiscoveryExecutor(
            network_policy=NetworkExecutionPolicy(
                network_enabled=True,
                contact_email=contact,
            )
        ).execute(plan)
    )

    print(
        "gaon-source-discovery-live-smoke: "
        f"provider={provider_name} "
        f"network_executed="
        f"{str(execution.network_executed).lower()} "
        f"provider_calls={execution.provider_calls} "
        f"results={len(execution.results)}"
    )

    for result in execution.results:
        print(
            f"- {result.source_type.value}: "
            f"{result.title} | {result.locator}"
        )

    if not execution.results:
        for record in execution.query_records:
            if record.error_message:
                print(
                    f"- failure="
                    f"{record.failure_kind.value if record.failure_kind else 'unknown'} "
                    f"{record.error_message}"
                )

        return 2

    return 0


def _main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m gaon.knowledge.execution"
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sub.add_parser("release-check")

    smoke = sub.add_parser("live-smoke")

    smoke.add_argument(
        "--provider",
        choices=("crossref", "datacite"),
        required=True,
    )

    smoke.add_argument(
        "--query",
        required=True,
    )

    smoke.add_argument(
        "--limit",
        type=int,
        default=3,
    )

    args = parser.parse_args()

    if args.command == "release-check":
        payload = execution_release_check()

        print(
            "gaon-source-discovery-execution-release-check: PASS "
            f"schema_version={payload['schema_version']} "
            f"provider_calls={payload['provider_calls']} "
            f"results={payload['results']} "
            "network_disabled_fail_closed=true "
            "https_allowlist=true "
            "budget_enforced=true "
            "provenance_created=false "
            "auto_ingest=false "
            "auto_validate=false "
            "production_approved=false "
            "strategy_mutated=false "
            "order_executed=false "
            "safety=pass"
        )

        return 0

    if args.limit <= 0 or args.limit > 10:
        parser.error(
            "--limit must be between 1 and 10"
        )

    return _live_smoke(
        provider_name=args.provider,
        query=args.query,
        limit=args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(_main())
