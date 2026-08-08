"""Sprint 174 — Bounded Source Content Acquisition.

Safely acquires actual source bytes from an explicitly supplied content URL.

Important boundaries:
- DOI/discovery locator is not automatically treated as source content
- content URL must be explicit
- network is disabled by default
- HTTPS only
- explicit host allowlist
- private / loopback / link-local destinations blocked
- MIME allowlist
- response byte budget
- timeout
- no cross-host redirects
- downloaded bytes remain inert evidence
- no claim extraction yet
- no knowledge validation
- no strategy mutation / Champion promotion / broker order
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import argparse
import hashlib
import ipaddress
import json
import mimetypes
from pathlib import Path
import socket
import tempfile
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from gaon.storage.foundation import GaonStorage

from .discovery import DiscoveryResult, DiscoveryStatus
from .ingestion import KnowledgeIngestor
from .provenance import SourceType, TrustLevel


CONTENT_ACQUISITION_SCHEMA_VERSION = 1

DEFAULT_MAX_CONTENT_BYTES = 5 * 1024 * 1024

ALLOWED_CONTENT_TYPES = (
    "text/plain",
    "text/html",
    "application/json",
    "application/pdf",
)


class ContentAcquisitionStatus(str, Enum):
    ACQUIRED = "acquired"
    BLOCKED = "blocked"
    FAILED = "failed"


class ContentFailureKind(str, Enum):
    NETWORK_DISABLED = "network_disabled"
    INVALID_URL = "invalid_url"
    HOST_NOT_ALLOWED = "host_not_allowed"
    NON_PUBLIC_DESTINATION = "non_public_destination"
    MIME_BLOCKED = "mime_blocked"
    SIZE_EXCEEDED = "size_exceeded"
    REDIRECT_BLOCKED = "redirect_blocked"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class ContentAcquisitionPolicy:
    network_enabled: bool = False
    allowed_hosts: tuple[str, ...] = ()
    allowed_content_types: tuple[str, ...] = ALLOWED_CONTENT_TYPES
    max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES
    timeout_seconds: float = 12.0
    user_agent: str = "StrategyLab-Gaon/0.1"
    require_https: bool = True
    allow_cross_host_redirects: bool = False

    def __post_init__(self) -> None:
        if self.max_content_bytes <= 0:
            raise ValueError("max_content_bytes must be positive")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        if not self.user_agent.strip():
            raise ValueError("user_agent is required")

        normalized = tuple(
            item.strip().lower()
            for item in self.allowed_hosts
        )

        for host in normalized:
            if (
                not host
                or "/" in host
                or ":" in host
                or "@" in host
            ):
                raise ValueError(
                    f"invalid allowed host: {host}"
                )

        if not self.allowed_content_types:
            raise ValueError(
                "allowed_content_types cannot be empty"
            )


@dataclass(frozen=True)
class ContentAcquisitionTarget:
    discovery_result_id: str
    source_locator: str
    content_url: str
    title: str
    source_type: SourceType

    @classmethod
    def from_discovery(
        cls,
        result: DiscoveryResult,
        *,
        content_url: str,
    ) -> "ContentAcquisitionTarget":
        if result.status is not DiscoveryStatus.DISCOVERED:
            raise ValueError(
                "only DISCOVERED results can become acquisition targets"
            )

        if result.knowledge_validated:
            raise ValueError(
                "prevalidated discovery result is not allowed"
            )

        if result.production_approved:
            raise ValueError(
                "production-approved discovery result is not allowed"
            )

        return cls(
            discovery_result_id=result.result_id,
            source_locator=result.locator,
            content_url=content_url.strip(),
            title=result.title,
            source_type=result.source_type,
        )


@dataclass(frozen=True)
class FetchPayload:
    final_url: str
    content_type: str
    content: bytes


class BinaryTransport(Protocol):
    def fetch(
        self,
        target: ContentAcquisitionTarget,
        *,
        policy: ContentAcquisitionPolicy,
    ) -> FetchPayload:
        ...


def _normalize_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _validate_public_destination(host: str) -> None:
    try:
        addresses = socket.getaddrinfo(
            host,
            443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(
            f"unable to resolve host: {host}"
        ) from exc

    if not addresses:
        raise ValueError(
            f"host resolved to no addresses: {host}"
        )

    for item in addresses:
        address = item[4][0]

        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError(
                f"invalid resolved address: {address}"
            ) from exc

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise PermissionError(
                f"non-public destination blocked: {address}"
            )


def validate_content_url(
    url: str,
    *,
    policy: ContentAcquisitionPolicy,
    resolve_dns: bool = True,
) -> str:
    value = url.strip()

    if not value:
        raise ValueError("content_url is required")

    parsed = urlparse(value)

    if policy.require_https and parsed.scheme != "https":
        raise PermissionError(
            "only HTTPS content acquisition is allowed"
        )

    if not parsed.hostname:
        raise ValueError("content_url hostname is required")

    if parsed.username or parsed.password:
        raise PermissionError(
            "URL userinfo is not allowed"
        )

    if parsed.port not in (None, 443):
        raise PermissionError(
            "non-standard HTTPS port is blocked"
        )

    host = parsed.hostname.lower()

    allowed = {
        item.lower()
        for item in policy.allowed_hosts
    }

    if host not in allowed:
        raise PermissionError(
            f"host is not allowlisted: {host}"
        )

    # Obvious literal-IP SSRF cases are blocked before DNS.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if (
            literal.is_private
            or literal.is_loopback
            or literal.is_link_local
            or literal.is_multicast
            or literal.is_reserved
            or literal.is_unspecified
        ):
            raise PermissionError(
                "non-public literal IP is blocked"
            )

    if resolve_dns:
        _validate_public_destination(host)

    return value


class SameHostRedirectHandler(HTTPRedirectHandler):
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
            or new.hostname.lower()
            != (old.hostname or "").lower()
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


class HttpsBinaryTransport:
    def fetch(
        self,
        target: ContentAcquisitionTarget,
        *,
        policy: ContentAcquisitionPolicy,
    ) -> FetchPayload:
        if not policy.network_enabled:
            raise PermissionError(
                "network execution is disabled"
            )

        url = validate_content_url(
            target.content_url,
            policy=policy,
            resolve_dns=True,
        )

        request = Request(
            url,
            headers={
                "User-Agent": policy.user_agent,
                "Accept": ", ".join(
                    policy.allowed_content_types
                ),
            },
            method="GET",
        )

        opener = build_opener(
            SameHostRedirectHandler()
        )

        with opener.open(
            request,
            timeout=policy.timeout_seconds,
        ) as response:
            final_url = response.geturl()

            parsed_original = urlparse(url)
            parsed_final = urlparse(final_url)

            if (
                parsed_final.scheme != "https"
                or not parsed_final.hostname
            ):
                raise PermissionError(
                    "unsafe final URL"
                )

            if (
                not policy.allow_cross_host_redirects
                and parsed_final.hostname.lower()
                != parsed_original.hostname.lower()
            ):
                raise PermissionError(
                    "cross-host redirect blocked"
                )

            content_type = _normalize_content_type(
                response.headers.get(
                    "Content-Type",
                    "",
                )
            )

            if (
                content_type
                not in policy.allowed_content_types
            ):
                raise TypeError(
                    f"blocked content type: {content_type or 'missing'}"
                )

            declared = response.headers.get(
                "Content-Length"
            )

            if declared:
                try:
                    declared_bytes = int(declared)
                except ValueError:
                    declared_bytes = 0

                if (
                    declared_bytes
                    > policy.max_content_bytes
                ):
                    raise OverflowError(
                        "declared content length exceeds budget"
                    )

            raw = response.read(
                policy.max_content_bytes + 1
            )

            if len(raw) > policy.max_content_bytes:
                raise OverflowError(
                    "content exceeds configured byte budget"
                )

            if not raw:
                raise ValueError(
                    "empty acquired content"
                )

        return FetchPayload(
            final_url=final_url,
            content_type=content_type,
            content=raw,
        )


@dataclass(frozen=True)
class ContentAcquisitionRecord:
    acquisition_id: str
    discovery_result_id: str
    source_locator: str
    content_url: str
    final_url: str | None
    content_type: str | None
    byte_count: int
    content_sha256: str | None
    status: ContentAcquisitionStatus
    failure_kind: ContentFailureKind | None
    error_message: str | None
    source_id: str | None
    raw_path: str | None
    metadata_path: str | None
    actual_source_body_fetched: bool
    stored_as_inert_evidence: bool
    eligible_for_claim_extraction: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version":
                CONTENT_ACQUISITION_SCHEMA_VERSION,
            "acquisition_id": self.acquisition_id,
            "discovery_result_id":
                self.discovery_result_id,
            "source_locator":
                self.source_locator,
            "content_url": self.content_url,
            "final_url": self.final_url,
            "content_type": self.content_type,
            "byte_count": self.byte_count,
            "content_sha256":
                self.content_sha256,
            "status": self.status.value,
            "failure_kind": (
                self.failure_kind.value
                if self.failure_kind
                else None
            ),
            "error_message":
                self.error_message,
            "source_id": self.source_id,
            "raw_path": self.raw_path,
            "metadata_path":
                self.metadata_path,
            "actual_source_body_fetched":
                self.actual_source_body_fetched,
            "stored_as_inert_evidence":
                self.stored_as_inert_evidence,
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


def canonical_acquisition_id(
    target: ContentAcquisitionTarget,
) -> str:
    encoded = json.dumps(
        {
            "discovery_result_id":
                target.discovery_result_id,
            "source_locator":
                target.source_locator,
            "content_url":
                target.content_url,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return (
        "content-acquisition:"
        + hashlib.sha256(encoded).hexdigest()
    )


def _suffix_for_type(
    content_type: str,
) -> str:
    explicit = {
        "text/plain": ".txt",
        "text/html": ".html",
        "application/json": ".json",
        "application/pdf": ".pdf",
    }

    return explicit.get(
        content_type,
        mimetypes.guess_extension(
            content_type
        )
        or ".bin",
    )


class BoundedSourceContentAcquirer:
    def __init__(
        self,
        storage: GaonStorage | None = None,
        *,
        policy: ContentAcquisitionPolicy | None = None,
        transport: BinaryTransport | None = None,
    ) -> None:
        self.storage = (
            storage or GaonStorage()
        )

        self.policy = (
            policy
            or ContentAcquisitionPolicy()
        )

        self.transport = (
            transport
            or HttpsBinaryTransport()
        )

        self.ingestor = KnowledgeIngestor(
            self.storage,
            max_source_bytes=(
                self.policy.max_content_bytes
            ),
        )

    def acquire(
        self,
        target: ContentAcquisitionTarget,
    ) -> ContentAcquisitionRecord:
        acquisition_id = (
            canonical_acquisition_id(
                target
            )
        )

        if not self.policy.network_enabled:
            return self._failure(
                acquisition_id,
                target,
                ContentFailureKind.NETWORK_DISABLED,
                "network execution is disabled",
            )

        try:
            # Fixture transports still pass the same structural URL policy;
            # DNS resolution belongs to the real HTTP transport.
            validate_content_url(
                target.content_url,
                policy=self.policy,
                resolve_dns=False,
            )

            payload = self.transport.fetch(
                target,
                policy=self.policy,
            )

            normalized_type = (
                _normalize_content_type(
                    payload.content_type
                )
            )

            if (
                normalized_type
                not in self.policy.allowed_content_types
            ):
                return self._failure(
                    acquisition_id,
                    target,
                    ContentFailureKind.MIME_BLOCKED,
                    (
                        "content type is not allowed: "
                        f"{normalized_type}"
                    ),
                )

            if (
                not payload.content
                or len(payload.content)
                > self.policy.max_content_bytes
            ):
                return self._failure(
                    acquisition_id,
                    target,
                    ContentFailureKind.SIZE_EXCEEDED,
                    "content byte budget exceeded or empty",
                )

            digest = hashlib.sha256(
                payload.content
            ).hexdigest()

            ingestion = (
                self.ingestor.ingest_bytes(
                    payload.content,
                    source_type=
                        target.source_type,
                    title=target.title,
                    # Provenance points to the
                    # actually acquired representation.
                    locator=payload.final_url,
                    trust_level=
                        TrustLevel.UNKNOWN,
                    notes=(
                        "artifact_scope="
                        "acquired_source_content; "
                        f"discovery_result_id="
                        f"{target.discovery_result_id}; "
                        f"source_locator="
                        f"{target.source_locator}; "
                        f"content_type="
                        f"{normalized_type}"
                    ),
                    suffix=_suffix_for_type(
                        normalized_type
                    ),
                )
            )

            if (
                ingestion.source.content_sha256
                != digest
            ):
                raise RuntimeError(
                    "stored provenance digest mismatch"
                )

            return ContentAcquisitionRecord(
                acquisition_id=acquisition_id,
                discovery_result_id=
                    target.discovery_result_id,
                source_locator=
                    target.source_locator,
                content_url=
                    target.content_url,
                final_url=
                    payload.final_url,
                content_type=
                    normalized_type,
                byte_count=
                    len(payload.content),
                content_sha256=digest,
                status=
                    ContentAcquisitionStatus.ACQUIRED,
                failure_kind=None,
                error_message=None,
                source_id=
                    ingestion.source.source_id,
                raw_path=
                    ingestion.raw_path,
                metadata_path=
                    ingestion.metadata_path,
                actual_source_body_fetched=True,
                stored_as_inert_evidence=True,
                # Parsing / extraction is Sprint 175+.
                eligible_for_claim_extraction=False,
            )

        except PermissionError as exc:
            message = str(exc)

            if "host" in message:
                kind = (
                    ContentFailureKind.HOST_NOT_ALLOWED
                )
            elif (
                "non-public"
                in message
                or "literal IP"
                in message
            ):
                kind = (
                    ContentFailureKind
                    .NON_PUBLIC_DESTINATION
                )
            else:
                kind = (
                    ContentFailureKind.INVALID_URL
                )

            return self._failure(
                acquisition_id,
                target,
                kind,
                message,
            )

        except TypeError as exc:
            return self._failure(
                acquisition_id,
                target,
                ContentFailureKind.MIME_BLOCKED,
                str(exc),
            )

        except OverflowError as exc:
            return self._failure(
                acquisition_id,
                target,
                ContentFailureKind.SIZE_EXCEEDED,
                str(exc),
            )

        except (
            socket.timeout,
            TimeoutError,
        ) as exc:
            return self._failure(
                acquisition_id,
                target,
                ContentFailureKind.TIMEOUT,
                str(exc),
            )

        except HTTPError as exc:
            kind = (
                ContentFailureKind.REDIRECT_BLOCKED
                if exc.code == 403
                and "redirect"
                in str(exc).lower()
                else ContentFailureKind.HTTP_ERROR
            )

            return self._failure(
                acquisition_id,
                target,
                kind,
                f"HTTP {exc.code}",
            )

        except URLError as exc:
            return self._failure(
                acquisition_id,
                target,
                ContentFailureKind.NETWORK_ERROR,
                str(exc.reason),
            )

        except (
            ValueError,
            RuntimeError,
        ) as exc:
            return self._failure(
                acquisition_id,
                target,
                ContentFailureKind.INVALID_RESPONSE,
                str(exc),
            )

    @staticmethod
    def _failure(
        acquisition_id: str,
        target: ContentAcquisitionTarget,
        kind: ContentFailureKind,
        message: str,
    ) -> ContentAcquisitionRecord:
        return ContentAcquisitionRecord(
            acquisition_id=acquisition_id,
            discovery_result_id=
                target.discovery_result_id,
            source_locator=
                target.source_locator,
            content_url=
                target.content_url,
            final_url=None,
            content_type=None,
            byte_count=0,
            content_sha256=None,
            status=
                ContentAcquisitionStatus.BLOCKED,
            failure_kind=kind,
            error_message=message,
            source_id=None,
            raw_path=None,
            metadata_path=None,
            actual_source_body_fetched=False,
            stored_as_inert_evidence=False,
        )


class FixtureBinaryTransport:
    """Deterministic test transport; no network."""

    def __init__(
        self,
        *,
        content_type: str = "text/plain",
        content: bytes = (
            b"Trend following results vary across market regimes."
        ),
    ) -> None:
        self.content_type = content_type
        self.content = content

    def fetch(
        self,
        target: ContentAcquisitionTarget,
        *,
        policy: ContentAcquisitionPolicy,
    ) -> FetchPayload:
        return FetchPayload(
            final_url=target.content_url,
            content_type=self.content_type,
            content=self.content,
        )


def content_acquisition_release_check(
    root: str | Path | None = None,
) -> Mapping[str, object]:
    storage = GaonStorage(root)

    result = DiscoveryResult(
        result_id="discovery-result:test",
        query_id="discovery-query:test",
        provider=(
            __import__(
                "gaon.knowledge.discovery",
                fromlist=["DiscoveryProvider"],
            ).DiscoveryProvider.ACADEMIC_SEARCH
        ),
        title="Trend Following Across Market Regimes",
        locator="https://doi.org/10.1000/test",
        source_type=SourceType.ACADEMIC_PAPER,
        status=DiscoveryStatus.DISCOVERED,
    )

    target = (
        ContentAcquisitionTarget.from_discovery(
            result,
            content_url=(
                "https://content.example.org/"
                "paper.txt"
            ),
        )
    )

    disabled = (
        BoundedSourceContentAcquirer(
            storage,
            policy=ContentAcquisitionPolicy(
                network_enabled=False,
                allowed_hosts=(
                    "content.example.org",
                ),
            ),
            transport=FixtureBinaryTransport(),
        ).acquire(target)
    )

    enabled = (
        BoundedSourceContentAcquirer(
            storage,
            policy=ContentAcquisitionPolicy(
                network_enabled=True,
                allowed_hosts=(
                    "content.example.org",
                ),
                max_content_bytes=1024 * 1024,
            ),
            transport=FixtureBinaryTransport(),
        ).acquire(target)
    )

    checks = {
        "network_disabled_fail_closed":
            disabled.status
            is ContentAcquisitionStatus.BLOCKED
            and disabled.failure_kind
            is ContentFailureKind.NETWORK_DISABLED,
        "content_acquired":
            enabled.status
            is ContentAcquisitionStatus.ACQUIRED,
        "body_fetched":
            enabled.actual_source_body_fetched,
        "stored_inert":
            enabled.stored_as_inert_evidence,
        "checksum_created":
            bool(enabled.content_sha256)
            and len(
                enabled.content_sha256
            ) == 64,
        "source_created":
            bool(enabled.source_id)
            and enabled.source_id.startswith(
                "source:"
            ),
        "raw_exists":
            bool(enabled.raw_path)
            and Path(
                enabled.raw_path
            ).is_file(),
        "metadata_exists":
            bool(enabled.metadata_path)
            and Path(
                enabled.metadata_path
            ).is_file(),
        "claim_extraction_not_run":
            enabled.eligible_for_claim_extraction
            is False,
        "knowledge_not_validated":
            enabled.knowledge_validated
            is False,
        "production_not_approved":
            enabled.production_approved
            is False,
        "strategy_not_mutated":
            enabled.strategy_mutated
            is False,
        "order_not_executed":
            enabled.order_executed
            is False,
    }

    if not all(checks.values()):
        failed = ",".join(
            key
            for key, value in checks.items()
            if not value
        )

        raise RuntimeError(
            "content acquisition release "
            f"check failed: {failed}"
        )

    return {
        "schema_version":
            CONTENT_ACQUISITION_SCHEMA_VERSION,
        "content_type":
            enabled.content_type,
        "byte_count":
            enabled.byte_count,
        "checks": checks,
        "safety": "pass",
    }


def _main() -> int:
    parser = argparse.ArgumentParser(
        prog=(
            "python -m "
            "gaon.knowledge.content_acquisition"
        )
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    release = sub.add_parser(
        "release-check"
    )

    release.add_argument(
        "--root",
        default=None,
    )

    live = sub.add_parser(
        "live-smoke"
    )

    live.add_argument(
        "--url",
        required=True,
    )

    live.add_argument(
        "--allow-host",
        required=True,
    )

    live.add_argument(
        "--title",
        default="Gaon live content acquisition",
    )

    args = parser.parse_args()

    if args.command == "release-check":
        if args.root:
            payload = (
                content_acquisition_release_check(
                    args.root
                )
            )
        else:
            with tempfile.TemporaryDirectory() as tmp:
                payload = (
                    content_acquisition_release_check(
                        tmp
                    )
                )

        print(
            "gaon-source-content-acquisition-release-check: PASS "
            f"schema_version={payload['schema_version']} "
            f"content_type={payload['content_type']} "
            f"bytes={payload['byte_count']} "
            "network_disabled_fail_closed=true "
            "https_only=true "
            "host_allowlist=true "
            "size_budget=true "
            "stored_inert=true "
            "claim_extraction=false "
            "knowledge_validated=false "
            "production_approved=false "
            "strategy_mutated=false "
            "order_executed=false "
            "safety=pass"
        )

        return 0

    host = urlparse(
        args.url
    ).hostname

    if not host:
        parser.error(
            "--url must contain a hostname"
        )

    if (
        host.lower()
        != args.allow_host.strip().lower()
    ):
        parser.error(
            "--allow-host must exactly match URL host"
        )

    result = DiscoveryResult(
        result_id=(
            "discovery-result:live-smoke"
        ),
        query_id=(
            "discovery-query:live-smoke"
        ),
        provider=(
            __import__(
                "gaon.knowledge.discovery",
                fromlist=["DiscoveryProvider"],
            ).DiscoveryProvider.OFFICIAL_WEB
        ),
        title=args.title,
        locator=args.url,
        source_type=
            SourceType.OFFICIAL_DOCUMENT,
        status=DiscoveryStatus.DISCOVERED,
    )

    target = (
        ContentAcquisitionTarget.from_discovery(
            result,
            content_url=args.url,
        )
    )

    with tempfile.TemporaryDirectory() as tmp:
        record = (
            BoundedSourceContentAcquirer(
                GaonStorage(tmp),
                policy=ContentAcquisitionPolicy(
                    network_enabled=True,
                    allowed_hosts=(
                        args.allow_host.strip().lower(),
                    ),
                ),
            ).acquire(target)
        )

        print(
            "gaon-source-content-live-smoke: "
            f"status={record.status.value} "
            f"failure="
            f"{record.failure_kind.value if record.failure_kind else 'none'} "
            f"content_type={record.content_type or 'none'} "
            f"bytes={record.byte_count} "
            f"body_fetched="
            f"{str(record.actual_source_body_fetched).lower()} "
            f"stored="
            f"{str(record.stored_as_inert_evidence).lower()}"
        )

        if record.error_message:
            print(
                f"- error={record.error_message}"
            )

        if record.status is not (
            ContentAcquisitionStatus.ACQUIRED
        ):
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
