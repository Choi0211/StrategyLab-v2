"""Safe evidence search providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
import time
from typing import Callable, Protocol
from urllib.parse import urlparse, urlunparse

from gaon.runtime.event_store import DurableEvent
from gaon.runtime.metrics import MetricsCollector


MAX_RESULTS = 20
MAX_CONTENT_CHARS = 8000


@dataclass(frozen=True)
class SearchQuery:
    query: str
    provider: str
    max_results: int = 5
    allowed_domains: tuple[str, ...] = ()
    denied_domains: tuple[str, ...] = ()
    timeout_seconds: float = 5.0
    max_content_chars: int = 4000


@dataclass(frozen=True)
class SourceMetadata:
    canonical_url: str
    domain: str
    retrieved_at: str
    provider: str


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    content: str
    source: SourceMetadata


class SearchProvider(Protocol):
    name: str
    enabled: bool
    def search(self, query: SearchQuery) -> tuple[SearchResult, ...]: ...


class FakeSearchProvider:
    name = "fake"

    def __init__(self, results: tuple[tuple[str, str, str], ...], *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._results = results

    def search(self, query: SearchQuery) -> tuple[SearchResult, ...]:
        if not self.enabled:
            raise PermissionError("search provider is disabled")
        return normalize_results(query, self.name, self._results)


class LocalFixtureSearchProvider(FakeSearchProvider):
    name = "local-fixture"


class RssAtomSearchProvider:
    name = "rss"
    enabled = True

    def __init__(self, feed_xml: str) -> None:
        self._feed_xml = feed_xml

    def search(self, query: SearchQuery) -> tuple[SearchResult, ...]:
        parser = _RssTitleLinkParser()
        parser.feed(self._feed_xml)
        rows = tuple((title, link, title) for title, link in parser.items)
        return normalize_results(query, self.name, rows)


class OptionalWebSearchProvider:
    name = "free-web"

    def __init__(self, fetcher: Callable[[SearchQuery], tuple[tuple[str, str, str], ...]], *, enabled: bool = False, retries: int = 1) -> None:
        self.enabled = enabled
        self._fetcher = fetcher
        self._retries = retries

    def search(self, query: SearchQuery) -> tuple[SearchResult, ...]:
        if not self.enabled:
            raise PermissionError("search provider is disabled")
        last: Exception | None = None
        started = time.perf_counter()
        for _ in range(max(self._retries, 1)):
            if time.perf_counter() - started > query.timeout_seconds:
                raise TimeoutError("search provider timed out")
            try:
                return normalize_results(query, self.name, self._fetcher(query))
            except TimeoutError:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise RuntimeError("search provider failed") from last


def normalize_results(query: SearchQuery, provider: str, rows: tuple[tuple[str, str, str], ...]) -> tuple[SearchResult, ...]:
    if query.max_results < 1 or query.max_results > MAX_RESULTS:
        raise ValueError("search max_results is out of bounds")
    if query.max_content_chars < 1 or query.max_content_chars > MAX_CONTENT_CHARS:
        raise ValueError("search max_content_chars is out of bounds")
    seen: set[str] = set()
    results: list[SearchResult] = []
    for title, url, content in rows:
        canonical = canonical_url(url)
        domain = urlparse(canonical).netloc.lower()
        if query.allowed_domains and domain not in query.allowed_domains:
            continue
        if domain in query.denied_domains:
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        clipped = content[: query.max_content_chars]
        results.append(
            SearchResult(
                title=title[:200],
                url=canonical,
                snippet=clipped[:500],
                content=clipped,
                source=SourceMetadata(canonical, domain, _now(), provider),
            )
        )
        if len(results) >= query.max_results:
            break
    return tuple(results)


def search_event(provider: str, count: int, *, occurred_at: str) -> DurableEvent:
    return DurableEvent(
        event_id=f"event:search:{provider}:{occurred_at}",
        event_type="SearchCompleted",
        occurred_at=occurred_at,
        actor_ref="system",
        correlation_id="search",
        causation_id=None,
        scope="research",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
        payload={"provider": provider, "count": count},
        evidence_refs=(),
        audit_refs=(),
        appended_at=occurred_at,
    )


def record_search_metrics(metrics: MetricsCollector, *, provider: str, count: int, failed: bool = False) -> None:
    metrics.increment("gaon_search_requests_total", provider=provider)
    metrics.gauge("gaon_evidence_items_total", count, provider=provider)
    if failed:
        metrics.increment("gaon_search_failures_total", provider=provider)


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path.rstrip("/") or "/", "", parsed.query, ""))


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class _RssTitleLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str]] = []
        self._current_tag = ""
        self._title = ""
        self._link = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag

    def handle_data(self, data: str) -> None:
        if self._current_tag == "title":
            self._title = data.strip()
        elif self._current_tag == "link":
            self._link = data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"item", "entry"} and self._title and self._link:
            self.items.append((self._title, self._link))
            self._title = ""
            self._link = ""
        self._current_tag = ""
