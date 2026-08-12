"""Follow-up A - autonomous external research execution orchestration.

This module wires the existing discovery, ingestion, acquisition,
normalization, claim bridging, and reevaluation components into one bounded
execution path. It does not introduce new provider systems.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import ipaddress
import socket
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .content_acquisition import (
    BoundedSourceContentAcquirer,
    ContentAcquisitionRecord,
    ContentAcquisitionPolicy,
    ContentAcquisitionStatus,
    ContentAcquisitionTarget,
    ContentFailureKind,
    validate_content_url,
)
from .content_claim_bridge import ContentClaimBridgeStatus, NormalizedContentClaimBridge
from .content_normalization import NormalizedContentRecord, SafeContentNormalizer
from .discovery import DiscoveryBudget, DiscoveryPolicy, DiscoveryStatus, SourceDiscoveryPlanner
from .discovery_ingestion import DiscoveryEvidenceIngestor
from .evidence_reevaluation import EvidenceConflictReevaluator, EvidenceReevaluationResult
from .execution import BoundedSourceDiscoveryExecutor, DiscoveryExecutionRun
from .gaps import ResearchQuestion
from .claims import KnowledgeCandidate
from .conflicts import ClaimStance
from .provenance import SourceProvenance


EXTERNAL_RESEARCH_EXECUTION_SCHEMA_VERSION = 1


class ExternalResearchTerminalState(str, Enum):
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    NO_NEW_RESEARCH_PATH = "no_new_research_path"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROVIDER_FAILURE = "provider_failure"
    CONTENT_UNAVAILABLE = "content_unavailable"
    NO_RELEVANT_RESEARCH_PATH = "no_relevant_research_path"
    DATA_FAILURE = "data_failure"


@dataclass(frozen=True)
class ExternalResearchExecutionPolicy:
    max_iterations: int = 1
    max_provider_calls: int = 2
    max_sources: int = 2
    max_total_download_bytes: int = 64_000
    content_network_enabled: bool = False
    allowed_content_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        if self.max_provider_calls <= 0:
            raise ValueError("max_provider_calls must be positive")
        if self.max_sources <= 0:
            raise ValueError("max_sources must be positive")
        if self.max_total_download_bytes <= 0:
            raise ValueError("max_total_download_bytes must be positive")


class ContentResolver(Protocol):
    def content_url_for(self, result_locator: str) -> str | None: ...


class AcademicRelevanceStatus(str, Enum):
    RELEVANT = "relevant"
    INSUFFICIENT_RELEVANCE = "insufficient_relevance"
    WRONG_DOMAIN = "wrong_domain"
    INSUFFICIENT_METADATA = "insufficient_metadata"


@dataclass(frozen=True)
class AcademicRelevanceRecord:
    discovery_result_id: str
    provider: str
    title: str
    doi: str | None
    relevance_status: AcademicRelevanceStatus
    relevance_score: int
    matched_research_terms: tuple[str, ...]
    matched_domain_terms: tuple[str, ...]
    matched_negative_terms: tuple[str, ...]
    rejected_reason: str | None
    selected_for_content_acquisition: bool

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": EXTERNAL_RESEARCH_EXECUTION_SCHEMA_VERSION,
            "discovery_result_id": self.discovery_result_id,
            "provider": self.provider,
            "title": self.title,
            "doi": self.doi,
            "relevance_status": self.relevance_status.value,
            "relevance_score": self.relevance_score,
            "matched_research_terms": list(self.matched_research_terms),
            "matched_domain_terms": list(self.matched_domain_terms),
            "matched_negative_terms": list(self.matched_negative_terms),
            "rejected_reason": self.rejected_reason,
            "selected_for_content_acquisition": self.selected_for_content_acquisition,
        }


class AcademicRelevanceScreener:
    """Deterministic financial/trading metadata relevance gate."""

    DOMAIN_TERMS = (
        "financial market",
        "financial markets",
        "asset price",
        "asset prices",
        "stock market",
        "equity market",
        "securities",
        "investment",
        "portfolio",
        "trading",
        "technical trading",
        "market timing",
        "returns",
        "price momentum",
    )
    RESEARCH_TERMS = (
        "breakout",
        "trend following",
        "time-series momentum",
        "time series momentum",
        "moving average",
        "technical analysis",
        "trading rule",
        "trading rules",
        "volume confirmation",
        "stop-loss",
        "stop loss",
        "trailing exit",
        "transaction cost",
        "out-of-sample",
        "out of sample",
        "robustness",
        "parameter sensitivity",
        "false breakout",
    )
    NEGATIVE_TERMS = (
        "tuple recovery",
        "replication independent",
        "distributed system",
        "distributed systems",
        "database recovery",
        "software architecture",
        "networking",
        "protocol",
        "data replication",
    )

    def screen(self, question: ResearchQuestion, result: object) -> AcademicRelevanceRecord:
        provider = getattr(getattr(result, "provider", ""), "value", str(getattr(result, "provider", "")))
        title = str(getattr(result, "title", "") or "")
        metadata = " ".join(
            item
            for item in (
                title,
                str(getattr(result, "abstract", "") or ""),
                " ".join(str(item) for item in getattr(result, "subjects", ()) or ()),
                str(getattr(result, "publisher", "") or ""),
                str(getattr(result, "container_title", "") or ""),
            )
            if item
        ).lower()
        title_text = title.lower().strip()
        matched_domain = _matched_terms(metadata, self.DOMAIN_TERMS)
        matched_research = _matched_terms(metadata, self.RESEARCH_TERMS)
        matched_negative = _matched_terms(metadata, self.NEGATIVE_TERMS)

        if not title_text:
            return self._record(result, provider, title, AcademicRelevanceStatus.INSUFFICIENT_METADATA, 0, matched_research, matched_domain, matched_negative, "missing_title")

        # Strong software/domain negatives are blocking unless the result also
        # names a financial/trading domain explicitly.
        if matched_negative and not matched_domain:
            return self._record(result, provider, title, AcademicRelevanceStatus.WRONG_DOMAIN, -3, matched_research, matched_domain, matched_negative, "negative_non_financial_domain")

        score = (2 * len(matched_domain)) + len(matched_research) - (3 * len(matched_negative))
        selected = bool(matched_domain and matched_research and score >= 3)
        if selected:
            return self._record(result, provider, title, AcademicRelevanceStatus.RELEVANT, score, matched_research, matched_domain, matched_negative, None)
        if not matched_domain:
            status = AcademicRelevanceStatus.WRONG_DOMAIN if matched_negative else AcademicRelevanceStatus.INSUFFICIENT_RELEVANCE
            reason = "no_financial_trading_domain"
        elif not matched_research:
            status = AcademicRelevanceStatus.INSUFFICIENT_RELEVANCE
            reason = "no_strategy_mechanism_match"
        else:
            status = AcademicRelevanceStatus.INSUFFICIENT_RELEVANCE
            reason = "score_below_threshold"
        return self._record(result, provider, title, status, score, matched_research, matched_domain, matched_negative, reason)

    def _record(
        self,
        result: object,
        provider: object,
        title: str,
        status: AcademicRelevanceStatus,
        score: int,
        matched_research: tuple[str, ...],
        matched_domain: tuple[str, ...],
        matched_negative: tuple[str, ...],
        reason: str | None,
    ) -> AcademicRelevanceRecord:
        return AcademicRelevanceRecord(
            discovery_result_id=str(getattr(result, "result_id", "")),
            provider=str(provider),
            title=title,
            doi=str(getattr(result, "doi", "") or "") or None,
            relevance_status=status,
            relevance_score=score,
            matched_research_terms=matched_research,
            matched_domain_terms=matched_domain,
            matched_negative_terms=matched_negative,
            rejected_reason=reason,
            selected_for_content_acquisition=status is AcademicRelevanceStatus.RELEVANT,
        )


class LocatorContentResolver:
    """Resolves only direct HTTPS content locators.

    DOI and metadata-only locators intentionally return None so the caller can
    report content_unavailable instead of pretending content was fetched.
    """

    def content_url_for(self, result_locator: str) -> str | None:
        value = result_locator.strip()
        if value.startswith("https://"):
            return value
        return None


class ContentResolutionStatus(str, Enum):
    DIRECT_CONTENT_URL = "direct_content_url"
    DOI_RESOLVED = "doi_resolved"
    METADATA_RESOURCE_URL = "metadata_resource_url"
    CONTENT_UNAVAILABLE = "content_unavailable"
    CONTENT_BLOCKED = "content_blocked"
    RESOLUTION_FAILURE = "resolution_failure"


@dataclass(frozen=True)
class ContentResolutionRecord:
    discovery_result_id: str
    provider: str
    title: str
    original_locator: str
    locator_kind: str
    doi: str | None
    resolution_attempted: bool
    status: ContentResolutionStatus
    resolved_content_url: str | None = None
    final_url: str | None = None
    final_host: str | None = None
    redirect_chain: tuple[str, ...] = ()
    failure_kind: str | None = None
    error_message: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": EXTERNAL_RESEARCH_EXECUTION_SCHEMA_VERSION,
            "discovery_result_id": self.discovery_result_id,
            "provider": self.provider,
            "title": self.title,
            "original_locator": self.original_locator,
            "locator_kind": self.locator_kind,
            "doi": self.doi,
            "resolution_attempted": self.resolution_attempted,
            "resolution_status": self.status.value,
            "resolved_content_url": self.resolved_content_url,
            "final_url": self.final_url,
            "final_host": self.final_host,
            "redirect_chain": list(self.redirect_chain),
            "failure_kind": self.failure_kind,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class ContentResolutionPayload:
    final_url: str
    redirect_chain: tuple[str, ...] = ()


class DoiResolutionTransport(Protocol):
    def resolve(
        self,
        url: str,
        *,
        policy: ContentAcquisitionPolicy,
    ) -> ContentResolutionPayload: ...


class _AcademicRedirectHandler(HTTPRedirectHandler):
    def __init__(self, *, policy: ContentAcquisitionPolicy, max_redirects: int) -> None:
        super().__init__()
        self.policy = policy
        self.max_redirects = max_redirects
        self.redirect_count = 0
        self.redirect_chain: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise HTTPError(req.full_url, 403, "redirect limit exceeded", headers, fp)
        _validate_doi_resolution_hop(newurl)
        self.redirect_chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpsDoiResolutionTransport:
    def resolve(
        self,
        url: str,
        *,
        policy: ContentAcquisitionPolicy,
    ) -> ContentResolutionPayload:
        validate_content_url(url, policy=policy, resolve_dns=True)
        handler = _AcademicRedirectHandler(policy=policy, max_redirects=policy.max_redirects)
        opener = build_opener(handler)
        request = Request(
            url,
            headers={"User-Agent": policy.user_agent, "Accept": ", ".join(policy.allowed_content_types)},
            method="GET",
        )
        with opener.open(request, timeout=policy.timeout_seconds) as response:
            final_url = response.geturl()
        validate_content_url(final_url, policy=policy, resolve_dns=True)
        return ContentResolutionPayload(final_url=final_url, redirect_chain=tuple(handler.redirect_chain))


class AcademicContentResolver:
    """Resolves academic locators without weakening generic content fetching."""

    def __init__(
        self,
        *,
        policy: ContentAcquisitionPolicy,
        doi_transport: DoiResolutionTransport | None = None,
    ) -> None:
        self.policy = policy
        self.doi_transport = doi_transport or HttpsDoiResolutionTransport()

    def content_url_for(self, result_locator: str) -> str | None:
        value = result_locator.strip()
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.scheme == "https" and parsed.hostname and parsed.hostname.lower() != "doi.org":
            return value
        return None

    def resolve(self, result: object) -> ContentResolutionRecord:
        locator = str(getattr(result, "locator", "") or "").strip()
        doi = str(getattr(result, "doi", "") or "").strip() or _doi_from_locator(locator)
        metadata_resource_url = str(getattr(result, "metadata_resource_url", "") or "").strip()
        provider = getattr(getattr(result, "provider", ""), "value", str(getattr(result, "provider", "")))
        locator_kind = _locator_kind(locator, doi=doi)
        base = {
            "discovery_result_id": str(getattr(result, "result_id", "")),
            "provider": str(provider),
            "title": str(getattr(result, "title", "")),
            "original_locator": locator,
            "locator_kind": locator_kind,
            "doi": doi or None,
        }

        if metadata_resource_url:
            return self._record_from_url(
                metadata_resource_url,
                status=ContentResolutionStatus.METADATA_RESOURCE_URL,
                resolution_attempted=True,
                **base,
            )

        if doi:
            doi_url = _doi_url(doi)
            try:
                payload = self.doi_transport.resolve(doi_url, policy=self.policy)
            except PermissionError as exc:
                return ContentResolutionRecord(
                    **base,
                    resolution_attempted=True,
                    status=ContentResolutionStatus.CONTENT_BLOCKED,
                    failure_kind="content_blocked",
                    error_message=str(exc),
                )
            except (HTTPError, TimeoutError, URLError, OSError, ValueError) as exc:
                return ContentResolutionRecord(
                    **base,
                    resolution_attempted=True,
                    status=ContentResolutionStatus.RESOLUTION_FAILURE,
                    failure_kind="resolution_failure",
                    error_message=str(exc),
                )
            return self._record_from_url(
                payload.final_url,
                status=ContentResolutionStatus.DOI_RESOLVED,
                resolution_attempted=True,
                redirect_chain=payload.redirect_chain,
                **base,
            )

        if locator.startswith("https://"):
            return self._record_from_url(
                locator,
                status=ContentResolutionStatus.DIRECT_CONTENT_URL,
                resolution_attempted=False,
                **base,
            )

        return ContentResolutionRecord(
            **base,
            resolution_attempted=False,
            status=ContentResolutionStatus.CONTENT_UNAVAILABLE,
            failure_kind="content_unavailable",
            error_message="no resolvable academic content locator",
        )

    def _record_from_url(
        self,
        url: str,
        *,
        status: ContentResolutionStatus,
        resolution_attempted: bool,
        discovery_result_id: str,
        provider: str,
        title: str,
        original_locator: str,
        locator_kind: str,
        doi: str | None,
        redirect_chain: tuple[str, ...] = (),
    ) -> ContentResolutionRecord:
        try:
            resolved = validate_content_url(url, policy=self.policy, resolve_dns=False)
        except PermissionError as exc:
            return ContentResolutionRecord(
                discovery_result_id=discovery_result_id,
                provider=provider,
                title=title,
                original_locator=original_locator,
                locator_kind=locator_kind,
                doi=doi,
                resolution_attempted=resolution_attempted,
                status=ContentResolutionStatus.CONTENT_BLOCKED,
                resolved_content_url=url,
                final_url=url,
                final_host=_host(url),
                redirect_chain=redirect_chain,
                failure_kind="content_blocked",
                error_message=str(exc),
            )
        except ValueError as exc:
            return ContentResolutionRecord(
                discovery_result_id=discovery_result_id,
                provider=provider,
                title=title,
                original_locator=original_locator,
                locator_kind=locator_kind,
                doi=doi,
                resolution_attempted=resolution_attempted,
                status=ContentResolutionStatus.CONTENT_UNAVAILABLE,
                resolved_content_url=url,
                final_url=url,
                final_host=_host(url),
                redirect_chain=redirect_chain,
                failure_kind="content_unavailable",
                error_message=str(exc),
            )
        return ContentResolutionRecord(
            discovery_result_id=discovery_result_id,
            provider=provider,
            title=title,
            original_locator=original_locator,
            locator_kind=locator_kind,
            doi=doi,
            resolution_attempted=resolution_attempted,
            status=status,
            resolved_content_url=resolved,
            final_url=resolved,
            final_host=_host(resolved),
            redirect_chain=redirect_chain,
        )


def _host(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).hostname.lower() if urlparse(url).hostname else None


def _validate_doi_resolution_hop(url: str) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise PermissionError("unsafe DOI redirect scheme is blocked")
    if not parsed.hostname:
        raise PermissionError("DOI redirect hostname is required")
    if parsed.username or parsed.password:
        raise PermissionError("URL userinfo is not allowed")
    if parsed.port not in (None, 80, 443):
        raise PermissionError("unsafe DOI redirect port is blocked")
    host = parsed.hostname.lower()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        _raise_if_non_public(literal)
        return
    for info in socket.getaddrinfo(host, None):
        _raise_if_non_public(ipaddress.ip_address(info[4][0]))


def _raise_if_non_public(address: ipaddress._BaseAddress) -> None:
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise PermissionError(f"non-public DOI redirect destination blocked: {address}")


def _matched_terms(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    found = []
    for term in terms:
        if term.lower() in text:
            found.append(term)
    return tuple(found)


def _doi_url(doi: str) -> str:
    value = doi.strip()
    if value.startswith("https://doi.org/"):
        return value
    if value.lower().startswith("doi:"):
        value = value[4:].strip()
    return f"https://doi.org/{value}"


def _doi_from_locator(locator: str) -> str | None:
    value = locator.strip()
    if not value:
        return None
    if value.startswith("10.") and "/" in value:
        return value
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.hostname and parsed.hostname.lower() == "doi.org":
        doi = parsed.path.lstrip("/")
        return doi or None
    return None


def _locator_kind(locator: str, *, doi: str | None) -> str:
    value = locator.strip()
    if doi and value.startswith("10."):
        return "doi"
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.hostname and parsed.hostname.lower() == "doi.org":
        return "doi_url"
    if parsed.scheme == "https":
        return "direct_https"
    if doi:
        return "doi"
    return "unknown"


@dataclass(frozen=True)
class AutonomousExternalResearchExecutionResult:
    state: ExternalResearchTerminalState
    question_id: str
    discovery_run: DiscoveryExecutionRun | None
    relevance_records: tuple[AcademicRelevanceRecord, ...]
    resolution_records: tuple[ContentResolutionRecord, ...]
    acquisition_records: tuple[ContentAcquisitionRecord, ...]
    normalized_records: tuple[NormalizedContentRecord, ...]
    candidates: tuple[KnowledgeCandidate, ...]
    reevaluation: EvidenceReevaluationResult | None
    provider_calls: int
    acquired_sources: int
    downloaded_bytes: int
    duplicate_results: int
    blockers: tuple[str, ...]
    network_executed: bool
    production_approved: bool = False
    knowledge_validated: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": EXTERNAL_RESEARCH_EXECUTION_SCHEMA_VERSION,
            "state": self.state.value,
            "question_id": self.question_id,
            "discovery_run": self.discovery_run.to_json() if self.discovery_run else None,
            "relevance_records": [item.to_json() for item in self.relevance_records],
            "resolution_records": [item.to_json() for item in self.resolution_records],
            "acquisition_records": [item.to_json() for item in self.acquisition_records],
            "normalized_records": [item.to_json() for item in self.normalized_records],
            "candidates": [item.to_json() for item in self.candidates],
            "reevaluation": self.reevaluation.to_json() if self.reevaluation else None,
            "provider_calls": self.provider_calls,
            "acquired_sources": self.acquired_sources,
            "downloaded_bytes": self.downloaded_bytes,
            "duplicate_results": self.duplicate_results,
            "blockers": list(self.blockers),
            "network_executed": self.network_executed,
            "production_approved": self.production_approved,
            "knowledge_validated": self.knowledge_validated,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


class AutonomousExternalResearchExecutor:
    def __init__(
        self,
        *,
        planner: SourceDiscoveryPlanner | None = None,
        discovery_executor: BoundedSourceDiscoveryExecutor | None = None,
        ingestion: DiscoveryEvidenceIngestor | None = None,
        acquirer: BoundedSourceContentAcquirer | None = None,
        normalizer: SafeContentNormalizer | None = None,
        claim_bridge: NormalizedContentClaimBridge | None = None,
        reevaluator: EvidenceConflictReevaluator | None = None,
        resolver: ContentResolver | None = None,
        relevance_screener: AcademicRelevanceScreener | None = None,
        policy: ExternalResearchExecutionPolicy | None = None,
    ) -> None:
        self.policy = policy or ExternalResearchExecutionPolicy()
        self.planner = planner or SourceDiscoveryPlanner(
            budget=DiscoveryBudget(
                max_queries=self.policy.max_provider_calls,
                max_results_per_query=self.policy.max_sources,
                max_total_results=self.policy.max_sources,
            )
        )
        self.discovery_executor = discovery_executor or BoundedSourceDiscoveryExecutor()
        self.ingestion = ingestion or DiscoveryEvidenceIngestor()
        self.acquirer = acquirer or BoundedSourceContentAcquirer(
            policy=ContentAcquisitionPolicy(
                network_enabled=self.policy.content_network_enabled,
                allowed_hosts=self.policy.allowed_content_hosts,
                max_content_bytes=self.policy.max_total_download_bytes,
            )
        )
        self.normalizer = normalizer or SafeContentNormalizer()
        self.claim_bridge = claim_bridge or NormalizedContentClaimBridge()
        self.reevaluator = reevaluator or EvidenceConflictReevaluator()
        self.resolver = resolver or LocatorContentResolver()
        self.relevance_screener = relevance_screener or AcademicRelevanceScreener()

    def run(
        self,
        question: ResearchQuestion,
        *,
        existing_candidates: tuple[KnowledgeCandidate, ...] = (),
        stances: Mapping[str, ClaimStance] | None = None,
    ) -> AutonomousExternalResearchExecutionResult:
        blockers: list[str] = []
        normalized: list[NormalizedContentRecord] = []
        acquisition_records: list[ContentAcquisitionRecord] = []
        relevance_records: list[AcademicRelevanceRecord] = []
        resolution_records: list[ContentResolutionRecord] = []
        candidates: list[KnowledgeCandidate] = []
        downloaded_bytes = 0
        acquired = 0
        seen_results: set[str] = set()

        plan = self.planner.build(question)
        execution = self.discovery_executor.execute(plan)
        if execution.provider_calls > self.policy.max_provider_calls:
            return self._result(ExternalResearchTerminalState.BUDGET_EXHAUSTED, question, execution, (), (), (), None, blockers, 0, 0)
        if not execution.results:
            state = (
                ExternalResearchTerminalState.PROVIDER_FAILURE
                if any(record.failure_kind for record in execution.query_records)
                else ExternalResearchTerminalState.NO_NEW_RESEARCH_PATH
            )
            return self._result(state, question, execution, (), (), (), None, blockers, 0, 0)

        try:
            self.ingestion.ingest_execution(execution)
        except ValueError as exc:
            blockers.append(f"discovery_ingestion_blocked:{exc}")

        source_by_id: dict[str, SourceProvenance] = {}
        selected_results: list[object] = []
        for result in execution.results:
            if result.result_id in seen_results:
                continue
            seen_results.add(result.result_id)
            relevance = self.relevance_screener.screen(question, result)
            relevance_records.append(relevance)
            if relevance.relevance_status is not AcademicRelevanceStatus.RELEVANT:
                blockers.append(f"{relevance.relevance_status.value}:{result.result_id}")
                continue
            selected_results.append(result)

        selected_results = sorted(
            selected_results,
            key=lambda item: next(
                record.relevance_score
                for record in relevance_records
                if record.discovery_result_id == str(getattr(item, "result_id", ""))
            ),
            reverse=True,
        )[: self.policy.max_sources]

        for result in selected_results:
            if not self.policy.content_network_enabled:
                blockers.append(f"content_unavailable:{result.result_id}")
                continue
            resolution = self._resolve_content(result)
            resolution_records.append(resolution)
            content_url = resolution.resolved_content_url
            if content_url is None or resolution.status in {
                ContentResolutionStatus.CONTENT_UNAVAILABLE,
                ContentResolutionStatus.CONTENT_BLOCKED,
                ContentResolutionStatus.RESOLUTION_FAILURE,
            }:
                blockers.append(f"{resolution.status.value}:{result.result_id}")
                continue
            target = ContentAcquisitionTarget.from_discovery(result, content_url=content_url)
            acquisition = self.acquirer.acquire(target)
            acquisition_records.append(acquisition)
            if acquisition.status is not ContentAcquisitionStatus.ACQUIRED:
                blockers.append(_content_blocker(result.result_id, acquisition.failure_kind))
                continue
            downloaded_bytes += acquisition.byte_count
            if downloaded_bytes > self.policy.max_total_download_bytes:
                blockers.append("budget_exhausted:download_bytes")
                return self._result(ExternalResearchTerminalState.BUDGET_EXHAUSTED, question, execution, tuple(acquisition_records), tuple(normalized), tuple(candidates), None, blockers, acquired, downloaded_bytes, tuple(resolution_records), tuple(relevance_records))
            acquired += 1
            source = SourceProvenance.create(
                source_type=result.source_type,
                title=result.title,
                locator=acquisition.source_locator,
                content_sha256=acquisition.content_sha256,
                trust_level=source_trust_level(result.source_type),
                ingested_at="2026-08-08T00:00:00+00:00",
                notes=f"discovery_result_id={result.result_id}; final_url={acquisition.final_url}",
            )
            source_by_id[acquisition.source_id] = source
            record = self.normalizer.normalize(acquisition, self._content_for(acquisition))
            normalized.append(record)
            bridge = self.claim_bridge.extract(record, source)
            if bridge.status is not ContentClaimBridgeStatus.EXTRACTED:
                blockers.append(f"claim_bridge_failed:{result.result_id}:{bridge.status.value}")
                continue
            candidates.extend(bridge.candidates)

        if blockers and not candidates:
            if relevance_records and not any(item.selected_for_content_acquisition for item in relevance_records):
                state = ExternalResearchTerminalState.NO_RELEVANT_RESEARCH_PATH
            else:
                state = ExternalResearchTerminalState.CONTENT_UNAVAILABLE
            return self._result(state, question, execution, tuple(acquisition_records), tuple(normalized), (), None, blockers, acquired, downloaded_bytes, tuple(resolution_records), tuple(relevance_records))
        if not candidates:
            return self._result(ExternalResearchTerminalState.NO_NEW_RESEARCH_PATH, question, execution, tuple(acquisition_records), tuple(normalized), (), None, blockers, acquired, downloaded_bytes, tuple(resolution_records), tuple(relevance_records))

        combined_candidates = tuple(existing_candidates) + tuple(candidates)
        reevaluation = self.reevaluator.reevaluate(
            topic_key=question.topic_key,
            candidates=combined_candidates,
            stances=stances or {candidate.candidate_id: ClaimStance.SUPPORTS for candidate in candidates},
        )
        if reevaluation.blockers:
            state = ExternalResearchTerminalState.DATA_FAILURE
        elif reevaluation.conflict is None or reevaluation.conflict.status.value == "no_conflict":
            state = ExternalResearchTerminalState.EVIDENCE_SUFFICIENT
        else:
            state = ExternalResearchTerminalState.UNRESOLVED_CONFLICT
        return self._result(state, question, execution, tuple(acquisition_records), tuple(normalized), tuple(candidates), reevaluation, blockers, acquired, downloaded_bytes, tuple(resolution_records), tuple(relevance_records))

    def _resolve_content(self, result: object) -> ContentResolutionRecord:
        resolve = getattr(self.resolver, "resolve", None)
        if callable(resolve):
            return resolve(result)
        content_url = self.resolver.content_url_for(str(getattr(result, "locator", "") or ""))
        provider = getattr(getattr(result, "provider", ""), "value", str(getattr(result, "provider", "")))
        if content_url is None:
            return ContentResolutionRecord(
                discovery_result_id=str(getattr(result, "result_id", "")),
                provider=str(provider),
                title=str(getattr(result, "title", "")),
                original_locator=str(getattr(result, "locator", "")),
                locator_kind=_locator_kind(str(getattr(result, "locator", "")), doi=None),
                doi=None,
                resolution_attempted=False,
                status=ContentResolutionStatus.CONTENT_UNAVAILABLE,
                failure_kind="content_unavailable",
                error_message="resolver returned no content URL",
            )
        return ContentResolutionRecord(
            discovery_result_id=str(getattr(result, "result_id", "")),
            provider=str(provider),
            title=str(getattr(result, "title", "")),
            original_locator=str(getattr(result, "locator", "")),
            locator_kind=_locator_kind(str(getattr(result, "locator", "")), doi=None),
            doi=None,
            resolution_attempted=False,
            status=ContentResolutionStatus.DIRECT_CONTENT_URL,
            resolved_content_url=content_url,
            final_url=content_url,
            final_host=_host(content_url),
        )

    def _content_for(self, acquisition: object) -> bytes:
        path = getattr(acquisition, "raw_path", "")
        if path:
            try:
                from pathlib import Path
                return Path(path).read_bytes()
            except OSError:
                pass
        return b""

    @staticmethod
    def _result(
        state: ExternalResearchTerminalState,
        question: ResearchQuestion,
        execution: DiscoveryExecutionRun | None,
        acquisition_records: tuple[ContentAcquisitionRecord, ...],
        normalized: tuple[NormalizedContentRecord, ...],
        candidates: tuple[KnowledgeCandidate, ...],
        reevaluation: EvidenceReevaluationResult | None,
        blockers: list[str],
        acquired: int,
        downloaded_bytes: int,
        resolution_records: tuple[ContentResolutionRecord, ...] = (),
        relevance_records: tuple[AcademicRelevanceRecord, ...] = (),
    ) -> AutonomousExternalResearchExecutionResult:
        return AutonomousExternalResearchExecutionResult(
            state=state,
            question_id=question.question_id,
            discovery_run=execution,
            relevance_records=relevance_records,
            resolution_records=resolution_records,
            acquisition_records=acquisition_records,
            normalized_records=normalized,
            candidates=candidates,
            reevaluation=reevaluation,
            provider_calls=execution.provider_calls if execution else 0,
            acquired_sources=acquired,
            downloaded_bytes=downloaded_bytes,
            duplicate_results=execution.duplicate_results if execution else 0,
            blockers=tuple(blockers),
            network_executed=bool(execution and execution.network_executed),
        )


def autonomous_external_research_execution_release_check() -> Mapping[str, object]:
    import tempfile

    from .discovery import DiscoveryProvider, DiscoveryResult
    from .execution import DiscoveryExecutionRun, QueryExecutionRecord
    from .conflicts import ConflictStatus
    from .gaps import KnowledgeGapType, RequiredEvidence, RequiredEvidenceType, ResearchPriority, ResearchQuestion, ResearchStopCondition
    from .provenance import SourceType
    from .content_acquisition import FetchPayload
    from .discovery_ingestion import DiscoveryEvidenceIngestor
    from gaon.storage.foundation import GaonStorage

    class FixtureDiscoveryExecutor:
        def execute(self, plan):  # type: ignore[no-untyped-def]
            result = DiscoveryResult(
                result_id="discovery-result:fixture",
                query_id=plan.queries[0].query_id,
                provider=DiscoveryProvider.ACADEMIC_SEARCH,
                title="Financial market breakout trading rule fixture research",
                locator="https://example.org/research.html",
                source_type=SourceType.RESEARCH_REPORT,
                status=DiscoveryStatus.DISCOVERED,
                abstract=(
                    "Fixture evidence about equity market trend following, "
                    "breakout rules, and out-of-sample robustness."
                ),
            )
            return DiscoveryExecutionRun(
                run_id="source-discovery-run:fixture",
                plan_id=plan.plan_id,
                network_enabled=False,
                network_executed=False,
                provider_calls=1,
                results=(result,),
                query_records=(QueryExecutionRecord(plan.queries[0].query_id, DiscoveryProvider.ACADEMIC_SEARCH, DiscoveryStatus.DISCOVERED, 1, 1, 1),),
                duplicate_results=0,
                budget_exhausted=False,
            )

    class FixtureTransport:
        def fetch(self, target, *, policy):  # type: ignore[no-untyped-def]
            return FetchPayload(
                final_url=target.content_url,
                content_type="text/html",
                content=b"<html><body>Claim: breakout filters can reduce false signals.</body></html>",
            )

    question = ResearchQuestion(
        question_id="research-question:external-execution",
        topic_key="strategy.breakout.robustness",
        gap_type=KnowledgeGapType.INSUFFICIENT_INDEPENDENCE,
        question="What evidence supports breakout robustness?",
        priority=ResearchPriority.HIGH,
        required_evidence=(RequiredEvidence(RequiredEvidenceType.INDEPENDENT_PRIMARY_SOURCE, 1, "release check"),),
        stop_conditions=(ResearchStopCondition.TWO_INDEPENDENT_PRIMARY_SOURCES,),
        parent_conflict_id="knowledge-conflict:external-execution",
        source_state=ConflictStatus.INSUFFICIENT_INDEPENDENCE,
    )
    with tempfile.TemporaryDirectory() as tmp:
        storage = GaonStorage(tmp)
        executor = AutonomousExternalResearchExecutor(
            discovery_executor=FixtureDiscoveryExecutor(),  # type: ignore[arg-type]
            ingestion=DiscoveryEvidenceIngestor(storage),
            acquirer=BoundedSourceContentAcquirer(
                storage,
                policy=ContentAcquisitionPolicy(
                    network_enabled=True,
                    allowed_hosts=("example.org",),
                    max_content_bytes=8_000,
                ),
                transport=FixtureTransport(),  # type: ignore[arg-type]
            ),
            policy=ExternalResearchExecutionPolicy(
                max_provider_calls=1,
                max_sources=1,
                max_total_download_bytes=8_000,
                content_network_enabled=True,
                allowed_content_hosts=("example.org",),
            ),
        )
        result = executor.run(question)
    checks = {
        "discovery": result.discovery_run is not None and len(result.discovery_run.results) == 1,
        "acquisition": result.acquired_sources == 1,
        "normalization": len(result.normalized_records) == 1,
        "claims": len(result.candidates) >= 1,
        "reevaluation": result.reevaluation is not None,
        "no_mutation": not result.strategy_mutated and not result.order_executed,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"autonomous external research execution release check failed: {failed}")
    return {
        "schema_version": EXTERNAL_RESEARCH_EXECUTION_SCHEMA_VERSION,
        "state": result.state.value,
        "provider_calls": result.provider_calls,
        "sources": result.acquired_sources,
        "claims": len(result.candidates),
        "checks": checks,
        "safety": "pass",
    }


def source_trust_level(source_type: object):
    from .provenance import SourceType, TrustLevel

    if source_type in (SourceType.ACADEMIC_PAPER, SourceType.OFFICIAL_DOCUMENT, SourceType.DATASET):
        return TrustLevel.HIGH
    if source_type is SourceType.RESEARCH_REPORT:
        return TrustLevel.MODERATE
    return TrustLevel.UNKNOWN


def _content_blocker(result_id: str, failure_kind: ContentFailureKind | None) -> str:
    value = failure_kind.value if failure_kind else "failed"
    if failure_kind is ContentFailureKind.MIME_BLOCKED:
        state = "unsupported_content_type"
    elif failure_kind in {
        ContentFailureKind.TIMEOUT,
        ContentFailureKind.NETWORK_ERROR,
        ContentFailureKind.HTTP_ERROR,
        ContentFailureKind.INVALID_RESPONSE,
    }:
        state = "fetch_failure"
    elif failure_kind in {
        ContentFailureKind.NETWORK_DISABLED,
        ContentFailureKind.INVALID_URL,
        ContentFailureKind.HOST_NOT_ALLOWED,
        ContentFailureKind.NON_PUBLIC_DESTINATION,
        ContentFailureKind.SIZE_EXCEEDED,
        ContentFailureKind.REDIRECT_BLOCKED,
    }:
        state = "content_blocked"
    else:
        state = "content_unavailable"
    return f"{state}:{result_id}:{value}"
