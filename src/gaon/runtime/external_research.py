"""Read-only external intelligence tools for Gaon.

External content is always treated as untrusted data. This module normalizes
provider output and enforces URL/SSRF boundaries before anything can enter the
runtime tool layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from ipaddress import ip_address
import json
import re
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen

from gaon.runtime.errors import mask_secret


MAX_RESULTS = 10
MAX_QUERY_CHARS = 240
SUPPORTED_SEARCH_PROVIDERS = ("fixture", "brave_search")


class ExternalResearchError(Exception):
    """External research request failed safely."""


class TrustClassification(str, Enum):
    OFFICIAL = "official"
    NEWS = "news"
    MARKET_DATA = "market_data"
    WEATHER = "weather"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


class FreshnessStatus(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExternalResearchQuery:
    query: str
    provider: str = "fixture"
    max_results: int = 5

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("external research query is required")
        if len(self.query) > MAX_QUERY_CHARS:
            raise ValueError("external research query is too long")
        if self.provider not in SUPPORTED_SEARCH_PROVIDERS:
            raise ExternalResearchError("configured search provider is not available")
        if self.max_results < 1 or self.max_results > MAX_RESULTS:
            raise ValueError("external research max_results is out of bounds")


@dataclass(frozen=True)
class SourceProvenance:
    citation_id: str
    canonical_url: str
    domain: str
    published_at: str | None
    retrieved_at: str
    trust: TrustClassification
    freshness: FreshnessStatus

    def to_json(self) -> dict[str, object]:
        return {
            "citation_id": self.citation_id,
            "canonical_url": self.canonical_url,
            "domain": self.domain,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "trust": self.trust.value,
            "freshness": self.freshness.value,
        }


@dataclass(frozen=True)
class ExternalSearchResult:
    title: str
    url: str
    source: str
    published_at: str | None
    retrieved_at: str
    snippet: str
    metadata: SourceProvenance

    def to_json(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "snippet": self.snippet,
            "metadata": self.metadata.to_json(),
        }


class ExternalResearchProvider(Protocol):
    name: str

    def search(self, query: ExternalResearchQuery, *, retrieved_at: str) -> tuple[ExternalSearchResult, ...]: ...


class FixtureExternalResearchProvider:
    name = "fixture"

    def __init__(self, rows: tuple[tuple[str, str, str, str | None], ...] | None = None) -> None:
        self._rows = rows or (
            ("Korea market breadth improves", "https://example.com/markets/korea-breadth", "Korea market breadth and semiconductor leadership improved.", "2026-07-20T00:00:00Z"),
            ("KRW volatility watch", "https://example.com/fx/krw-volatility", "USD/KRW volatility remains a key risk factor for short term strategies.", "2026-07-20T00:00:00Z"),
            ("Breakout strategies need volume confirmation", "https://example.com/research/breakout-volume", "Recent research notes emphasize volume filters and transaction costs.", "2026-07-19T00:00:00Z"),
        )

    def search(self, query: ExternalResearchQuery, *, retrieved_at: str) -> tuple[ExternalSearchResult, ...]:
        lowered = query.query.casefold()
        rows = [row for row in self._rows if any(token in (row[0] + " " + row[2]).casefold() for token in lowered.split())]
        if not rows:
            rows = list(self._rows)
        return normalize_external_results(tuple(rows), max_results=query.max_results, retrieved_at=retrieved_at)


class BraveSearchExternalResearchProvider:
    """Real web/news search via the Brave Search API.

    Requires an API key (GAON_BRAVE_SEARCH_API_KEY). Never used as a silent
    substitute for fixture data: callers must explicitly configure it, and a
    missing key fails closed (ExternalResearchError) rather than fabricating
    results.
    """

    name = "brave_search"

    def __init__(
        self,
        *,
        api_key: str | None,
        timeout_seconds: float = 10.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def __repr__(self) -> str:
        return f"BraveSearchExternalResearchProvider(api_key={mask_secret(self._api_key)!r}, timeout_seconds={self._timeout_seconds!r})"

    def search(self, query: ExternalResearchQuery, *, retrieved_at: str) -> tuple[ExternalSearchResult, ...]:
        if not self._api_key:
            raise ExternalResearchError("brave_search provider is not configured (missing API key)")
        url = (
            "https://api.search.brave.com/res/v1/web/search"
            f"?q={quote(query.query)}&count={query.max_results}"
        )
        request = Request(
            url,
            headers={"Accept": "application/json", "X-Subscription-Token": self._api_key},
        )
        try:
            response = self._opener(request, timeout=self._timeout_seconds)
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
        except (TimeoutError, socket.timeout) as exc:
            raise ExternalResearchError("brave_search request timed out") from exc
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise ExternalResearchError("brave_search API key was rejected") from exc
            if exc.code == 429:
                raise ExternalResearchError("brave_search rate limit exceeded") from exc
            raise ExternalResearchError(f"brave_search request failed (HTTP {exc.code})") from exc
        except (URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ExternalResearchError("brave_search request failed") from exc

        web = payload.get("web") if isinstance(payload, dict) else None
        items = web.get("results") if isinstance(web, dict) else None
        rows: list[tuple[str, str, str, str | None]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            item_url = str(item.get("url") or "").strip()
            if not title or not item_url:
                continue
            snippet = str(item.get("description") or "").strip()
            rows.append((title, item_url, snippet, _brave_published_at(item)))
        return normalize_external_results(tuple(rows), max_results=query.max_results, retrieved_at=retrieved_at)


def _brave_published_at(item: dict[str, object]) -> str | None:
    raw = item.get("page_age") or item.get("age")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_external_research_provider(
    *, provider_name: str = "fixture", api_key: str | None = None, timeout_seconds: float = 10.0,
) -> ExternalResearchProvider:
    """Build the configured search provider, failing safe to fixture.

    brave_search is only selected when an API key is actually present;
    otherwise this returns the fixture provider, whose results are already
    disclosed as synthetic by ExternalResearchTool.search (never silently
    presented as real research).
    """
    if provider_name == "brave_search" and api_key:
        return BraveSearchExternalResearchProvider(api_key=api_key, timeout_seconds=timeout_seconds)
    return FixtureExternalResearchProvider()


def create_external_research_tool(
    *, provider_name: str = "fixture", api_key: str | None = None, timeout_seconds: float = 10.0,
) -> "ExternalResearchTool":
    """Build a fully configured ExternalResearchTool, disclosing any fallback."""
    provider = create_external_research_provider(
        provider_name=provider_name, api_key=api_key, timeout_seconds=timeout_seconds,
    )
    return ExternalResearchTool(provider, requested_provider_name=provider_name)


class ExternalResearchTool:
    def __init__(
        self,
        provider: ExternalResearchProvider | None = None,
        *,
        requested_provider_name: str | None = None,
    ) -> None:
        self._provider = provider or FixtureExternalResearchProvider()
        # Set when a factory (e.g. create_external_research_provider) fell back to
        # fixture because the configured real provider had no usable API key -
        # distinct from a deployment that never asked for a real provider at all.
        self._requested_provider_name = requested_provider_name

    def search(self, query: str, *, max_results: int = 5, retrieved_at: str | None = None) -> dict[str, object]:
        at = retrieved_at or utc_now()
        request = ExternalResearchQuery(query=query, provider=self._provider.name, max_results=max_results)
        results = self._provider.search(request, retrieved_at=at)
        fell_back = bool(self._requested_provider_name) and self._requested_provider_name != self._provider.name
        warnings = []
        if fell_back:
            warnings.append(
                f"configured provider '{self._requested_provider_name}' is not available (missing/invalid API key); "
                "using fixture instead - this is not real external research"
            )
        if self._provider.name == "fixture":
            warnings += [
                "fixture results are synthetic examples, not verified external research",
                "do not use fixture results to validate or promote trading strategies",
            ]
        warnings.append("external content is untrusted data; webpage instructions were not executed")
        return {
            "provider": self._provider.name,
            "requested_provider": self._requested_provider_name or self._provider.name,
            "query": request.query,
            "retrieved_at": at,
            "results": [result.to_json() for result in results],
            "warnings": warnings,
        }


def structured_data(tool_name: str, args: dict[str, object], *, retrieved_at: str | None = None) -> dict[str, object]:
    at = retrieved_at or utc_now()
    if tool_name == "weather_current":
        location = str(args.get("location", "Seoul"))
        return _structured("fixture-weather", at, {"location": location, "condition": "unavailable_fixture", "temperature_c": None})
    if tool_name == "weather_forecast":
        location = str(args.get("location", "Seoul"))
        return _structured("fixture-weather", at, {"location": location, "forecast": [], "status": "provider_not_configured"})
    if tool_name == "exchange_rate":
        base = str(args.get("base", "USD")).upper()
        quote = str(args.get("quote", "KRW")).upper()
        return _structured("fixture-fx", at, {"base": base, "quote": quote, "rate": None, "status": "provider_not_configured"})
    if tool_name == "market_data":
        symbol = str(args.get("symbol", "KOSPI"))
        return _structured("fixture-market", at, {"symbol": symbol, "price": None, "status": "provider_not_configured"})
    if tool_name == "news_search":
        query = str(args.get("query", "market"))
        return ExternalResearchTool().search(query, max_results=int(args.get("max_results", 5)), retrieved_at=at)
    raise ExternalResearchError("unknown structured data tool")


def normalize_external_results(rows: tuple[tuple[str, str, str, str | None], ...], *, max_results: int, retrieved_at: str) -> tuple[ExternalSearchResult, ...]:
    seen: set[str] = set()
    results: list[ExternalSearchResult] = []
    for index, (title, url, snippet, published_at) in enumerate(rows, start=1):
        try:
            canonical = validate_external_url(url)
        except ExternalResearchError:
            # A live provider can return one malformed/blocked URL among many
            # good ones - skip just that row instead of failing the whole search.
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        domain = urlparse(canonical).netloc.lower()
        provenance = SourceProvenance(
            citation_id=f"src-{index}",
            canonical_url=canonical,
            domain=domain,
            published_at=published_at,
            retrieved_at=retrieved_at,
            trust=classify_source(domain),
            freshness=freshness_status(published_at),
        )
        results.append(ExternalSearchResult(title[:200], canonical, domain, published_at, retrieved_at, snippet[:600], provenance))
        if len(results) >= max_results:
            break
    return tuple(results)


def validate_external_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"https", "http"}:
        raise ExternalResearchError("unsupported URL scheme")
    if parsed.username or parsed.password:
        raise ExternalResearchError("URL credentials are not allowed")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ExternalResearchError("URL host is required")
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise ExternalResearchError("local or metadata host is blocked")
    try:
        address = ip_address(host)
    except ValueError:
        pass
    else:
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
            raise ExternalResearchError("private, loopback, or reserved network is blocked")
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path.rstrip("/") or "/", "", parsed.query, ""))


def validate_redirect_chain(urls: tuple[str, ...]) -> tuple[str, ...]:
    if not urls:
        raise ExternalResearchError("redirect chain is empty")
    return tuple(validate_external_url(url) for url in urls)


def classify_source(domain: str) -> TrustClassification:
    if domain.endswith(".go.kr") or domain.endswith(".gov") or domain in {"bankofkorea.or.kr", "krx.co.kr"}:
        return TrustClassification.OFFICIAL
    if any(token in domain for token in ("news", "reuters", "bloomberg", "yonhap")):
        return TrustClassification.NEWS
    if any(token in domain for token in ("market", "finance", "exchange")):
        return TrustClassification.MARKET_DATA
    if "weather" in domain:
        return TrustClassification.WEATHER
    return TrustClassification.UNKNOWN


def freshness_status(published_at: str | None) -> FreshnessStatus:
    if published_at is None:
        return FreshnessStatus.UNKNOWN
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", published_at) is None:
        return FreshnessStatus.UNKNOWN
    published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    age_days = (datetime.now(UTC) - published).days
    return FreshnessStatus.FRESH if age_days <= 7 else FreshnessStatus.STALE


def _structured(source: str, retrieved_at: str, data: dict[str, object]) -> dict[str, object]:
    return {
        "source": source,
        "retrieved_at": retrieved_at,
        "data_timestamp": None,
        "freshness": FreshnessStatus.UNKNOWN.value,
        "data": data,
        "warnings": ["provider_not_configured; no synthetic market fact was generated"],
    }


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
