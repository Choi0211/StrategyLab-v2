"""Bounded production adapters for real external research sources.

This module plugs concrete production providers into the existing
``MultiSourceResearchOrchestrator`` contract. It intentionally does not create
a second research engine, does not mutate strategies, and never executes orders.

Provider policy:

* Corporate: Samsung Electronics official IR pages for 005930, or explicitly
  configured HTTPS URLs for other symbols.
* Regulatory: OpenDART. Requires ``GAON_DART_API_KEY`` and uses the official
  disclosure search + original-document APIs. Credentials are never persisted
  into evidence locators.
* News: bounded Google News RSS discovery. News claims are idea evidence only,
  never validation evidence.
* Professional research / Web: opt-in HTTPS URL lists supplied by environment;
  hosts must be explicitly allowlisted.

All fetches are HTTPS-only, host-allowlisted, bounded by timeout/bytes, and
fail closed. Unconfigured providers report NOT_CONFIGURED honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import io
import ipaddress
import json
import os
import re
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

from .multi_source_research import (
    AcquisitionState,
    ClaimStance,
    CredibilityTier,
    MultiSourceResearchPlan,
    ProviderResearchReport,
    ProviderState,
    SourceCategory,
    UnifiedAcquiredSource,
    UnifiedClaim,
    UnifiedDiscoveryResult,
)


PRODUCTION_PROVIDER_TIMEOUT_SECONDS = 10.0
PRODUCTION_PROVIDER_MAX_RESPONSE_BYTES = 384 * 1024
PRODUCTION_PROVIDER_MAX_TEXT_CHARS = 12_000
PRODUCTION_PROVIDER_USER_AGENT = "StrategyLab-Gaon/2.0 (+bounded research adapter)"

SAMSUNG_IR_URLS = (
    "https://www.samsung.com/global/ir/",
    "https://www.samsung.com/global/ir/reports-disclosures/public-disclosure/",
    "https://www.samsung.com/global/ir/financial-information/earnings-release/",
)
SAMSUNG_IR_ALLOWED_HOSTS = ("www.samsung.com",)

DART_ALLOWED_HOSTS = ("opendart.fss.or.kr",)
DART_CORP_CODES = {"005930": "00126380"}

GOOGLE_NEWS_ALLOWED_HOSTS = ("news.google.com",)


@dataclass(frozen=True)
class FetchResult:
    final_url: str
    content_type: str
    body: bytes


FetchCallable = Callable[[str, tuple[str, ...]], FetchResult]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def production_external_provider_adapters(*, symbol: str) -> tuple[object, ...]:
    """Return concrete adapters for the five production external categories."""

    return (
        ProductionCorporateAdapter(symbol=symbol),
        ProductionDartRegulatoryAdapter(symbol=symbol),
        ProductionNewsRssAdapter(symbol=symbol),
        ProductionConfiguredUrlAdapter(
            category=SourceCategory.PROFESSIONAL_RESEARCH,
            provider="production:professional_research:https",
            urls_env="GAON_PROFESSIONAL_RESEARCH_URLS",
            allowed_hosts_env="GAON_PROFESSIONAL_RESEARCH_ALLOWED_HOSTS",
            credibility=CredibilityTier.TIER_B_RESEARCH_PROFESSIONAL,
            validation_evidence=True,
        ),
        ProductionConfiguredUrlAdapter(
            category=SourceCategory.WEB,
            provider="production:web:https",
            urls_env="GAON_WEB_RESEARCH_URLS",
            allowed_hosts_env="GAON_WEB_RESEARCH_ALLOWED_HOSTS",
            credibility=CredibilityTier.TIER_C_SECONDARY_INFORMATIONAL,
            validation_evidence=False,
        ),
    )


class ProductionCorporateAdapter:
    category = SourceCategory.CORPORATE
    provider = "production:corporate:official_ir"

    def __init__(self, *, symbol: str, fetcher: FetchCallable | None = None) -> None:
        self._symbol = symbol
        self._fetcher = fetcher or _fetch_https

    def research(self, plan: MultiSourceResearchPlan) -> ProviderResearchReport:
        queries = tuple(plan.queries.get(self.category.value, ()))
        urls, hosts = self._configuration()
        if not urls:
            return _not_configured(self.provider, self.category, queries, "corporate_urls_not_configured")
        return _research_html_urls(
            provider=self.provider,
            category=self.category,
            plan=plan,
            queries=queries,
            urls=urls,
            allowed_hosts=hosts,
            fetcher=self._fetcher,
            credibility=CredibilityTier.TIER_A_AUTHORITATIVE,
            validation_evidence=True,
        )

    def _configuration(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        configured_urls = _csv_env("GAON_CORPORATE_RESEARCH_URLS")
        configured_hosts = _csv_env("GAON_CORPORATE_RESEARCH_ALLOWED_HOSTS")
        if configured_urls:
            return configured_urls, configured_hosts
        if self._symbol == "005930":
            return SAMSUNG_IR_URLS, SAMSUNG_IR_ALLOWED_HOSTS
        return (), ()


class ProductionDartRegulatoryAdapter:
    category = SourceCategory.REGULATORY
    provider = "production:regulatory:opendart"

    def __init__(self, *, symbol: str, fetcher: FetchCallable | None = None) -> None:
        self._symbol = symbol
        self._fetcher = fetcher or _fetch_https

    def research(self, plan: MultiSourceResearchPlan) -> ProviderResearchReport:
        queries = tuple(plan.queries.get(self.category.value, ()))
        api_key = os.environ.get("GAON_DART_API_KEY", "").strip()
        corp_code = _dart_corp_code(self._symbol)
        if not api_key:
            return _not_configured(self.provider, self.category, queries, "GAON_DART_API_KEY_missing")
        if not corp_code:
            return _not_configured(self.provider, self.category, queries, "dart_corp_code_missing")

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=370)
        list_url = _url_with_query(
            "https://opendart.fss.or.kr/api/list.json",
            {
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": start.strftime("%Y%m%d"),
                "end_de": now.strftime("%Y%m%d"),
                "page_count": "20",
                "sort": "date",
                "sort_mth": "desc",
            },
        )
        try:
            listing = self._fetcher(list_url, DART_ALLOWED_HOSTS)
            payload = json.loads(listing.body.decode("utf-8"))
        except Exception as exc:
            return _provider_failure(self.provider, self.category, queries, f"dart_list_failure:{type(exc).__name__}")

        if str(payload.get("status")) != "000":
            message = str(payload.get("message") or payload.get("status") or "dart_error")
            return ProviderResearchReport(
                self.provider,
                self.category,
                ProviderState.CONTENT_UNAVAILABLE,
                queries,
                blockers=(f"dart_api:{message}",),
                fixture_backed=False,
            )

        filings = [item for item in payload.get("list", []) if isinstance(item, dict)]
        if not filings:
            return ProviderResearchReport(
                self.provider,
                self.category,
                ProviderState.NO_RESULTS,
                queries,
                blockers=("dart_no_filings",),
                fixture_backed=False,
            )

        document_texts: list[str] = []
        document_ids: list[str] = []
        for filing in filings[:2]:
            receipt = str(filing.get("rcept_no") or "")
            if not re.fullmatch(r"\d{14}", receipt):
                continue
            document_url = _url_with_query(
                "https://opendart.fss.or.kr/api/document.xml",
                {"crtfc_key": api_key, "rcept_no": receipt},
            )
            try:
                document = self._fetcher(document_url, DART_ALLOWED_HOSTS)
                text = _text_from_dart_zip(document.body)
            except Exception:
                continue
            if text:
                report_name = str(filing.get("report_nm") or "DART disclosure")
                filed_at = str(filing.get("rcept_dt") or "unknown")
                document_texts.append(f"{report_name} ({filed_at})\n{text}")
                document_ids.append(receipt)

        if not document_texts:
            return ProviderResearchReport(
                self.provider,
                self.category,
                ProviderState.CONTENT_UNAVAILABLE,
                queries,
                blockers=("dart_documents_unavailable",),
                fixture_backed=False,
            )

        combined = _clip_text("\n\n".join(document_texts))
        locator = f"https://opendart.fss.or.kr/disclosures/{corp_code}"
        return _single_text_report(
            provider=self.provider,
            category=self.category,
            plan=plan,
            queries=queries,
            title=f"{self._symbol} OpenDART disclosure documents",
            locator=locator,
            publisher="Financial Supervisory Service OpenDART",
            text=combined,
            content_type="application/zip+xml",
            credibility=CredibilityTier.TIER_A_AUTHORITATIVE,
            validation_evidence=True,
            metadata={"corp_code": corp_code, "receipt_numbers": document_ids},
        )


class ProductionNewsRssAdapter:
    category = SourceCategory.NEWS
    provider = "production:news:rss"

    def __init__(self, *, symbol: str, fetcher: FetchCallable | None = None) -> None:
        self._symbol = symbol
        self._fetcher = fetcher or _fetch_https

    def research(self, plan: MultiSourceResearchPlan) -> ProviderResearchReport:
        queries = tuple(plan.queries.get(self.category.value, ()))
        if os.environ.get("GAON_NEWS_RSS_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
            return _not_configured(self.provider, self.category, queries, "GAON_NEWS_RSS_ENABLED=false")

        query = (queries[0] if queries else f"{self._symbol} Samsung Electronics")[:220]
        base = os.environ.get("GAON_NEWS_RSS_BASE_URL", "https://news.google.com/rss/search").strip()
        parsed = urlparse(base)
        if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() not in GOOGLE_NEWS_ALLOWED_HOSTS:
            return _provider_failure(self.provider, self.category, queries, "news_rss_base_url_not_allowed")
        url = _url_with_query(base, {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        try:
            feed = self._fetcher(url, GOOGLE_NEWS_ALLOWED_HOSTS)
            root = ET.fromstring(feed.body)
        except Exception as exc:
            return _provider_failure(self.provider, self.category, queries, f"news_rss_failure:{type(exc).__name__}")

        rows: list[str] = []
        publishers: list[str] = []
        for item in root.findall(".//item")[:5]:
            title = " ".join((item.findtext("title") or "").split())
            source = " ".join((item.findtext("source") or "").split())
            published = " ".join((item.findtext("pubDate") or "").split())
            if title:
                rows.append(f"{title} | publisher={source or 'unknown'} | published={published or 'unknown'}")
                if source:
                    publishers.append(source)
        if not rows:
            return ProviderResearchReport(
                self.provider,
                self.category,
                ProviderState.NO_RESULTS,
                queries,
                blockers=("news_rss_no_items",),
                fixture_backed=False,
            )

        return _single_text_report(
            provider=self.provider,
            category=self.category,
            plan=plan,
            queries=queries,
            title=f"{self._symbol} bounded news RSS",
            locator=_redact_query(url),
            publisher="Google News RSS",
            text="\n".join(rows),
            content_type=feed.content_type,
            credibility=CredibilityTier.TIER_C_SECONDARY_INFORMATIONAL,
            validation_evidence=False,
            metadata={"publishers": publishers[:5], "item_count": len(rows)},
        )


class ProductionConfiguredUrlAdapter:
    """Opt-in bounded HTTPS adapter for professional research or general web."""

    def __init__(
        self,
        *,
        category: SourceCategory,
        provider: str,
        urls_env: str,
        allowed_hosts_env: str,
        credibility: CredibilityTier,
        validation_evidence: bool,
        fetcher: FetchCallable | None = None,
    ) -> None:
        self.category = category
        self.provider = provider
        self._urls_env = urls_env
        self._allowed_hosts_env = allowed_hosts_env
        self._credibility = credibility
        self._validation_evidence = validation_evidence
        self._fetcher = fetcher or _fetch_https

    def research(self, plan: MultiSourceResearchPlan) -> ProviderResearchReport:
        queries = tuple(plan.queries.get(self.category.value, ()))
        urls = _csv_env(self._urls_env)
        hosts = _csv_env(self._allowed_hosts_env)
        if not urls or not hosts:
            return _not_configured(self.provider, self.category, queries, f"{self._urls_env}_or_allowlist_missing")
        return _research_html_urls(
            provider=self.provider,
            category=self.category,
            plan=plan,
            queries=queries,
            urls=urls,
            allowed_hosts=hosts,
            fetcher=self._fetcher,
            credibility=self._credibility,
            validation_evidence=self._validation_evidence,
        )


def _research_html_urls(
    *,
    provider: str,
    category: SourceCategory,
    plan: MultiSourceResearchPlan,
    queries: tuple[str, ...],
    urls: tuple[str, ...],
    allowed_hosts: tuple[str, ...],
    fetcher: FetchCallable,
    credibility: CredibilityTier,
    validation_evidence: bool,
) -> ProviderResearchReport:
    texts: list[str] = []
    succeeded: list[str] = []
    failures: list[str] = []
    for url in urls[:3]:
        try:
            result = fetcher(url, allowed_hosts)
            text = _text_from_payload(result.body, result.content_type)
            if text:
                texts.append(text)
                succeeded.append(result.final_url)
        except Exception as exc:
            failures.append(f"{urlparse(url).hostname or 'unknown'}:{type(exc).__name__}")
    if not texts:
        return ProviderResearchReport(
            provider,
            category,
            ProviderState.CONTENT_UNAVAILABLE if failures else ProviderState.NO_RESULTS,
            queries,
            blockers=tuple(failures or ("no_usable_content",)),
            fixture_backed=False,
        )
    return _single_text_report(
        provider=provider,
        category=category,
        plan=plan,
        queries=queries,
        title=f"{category.value} bounded production evidence",
        locator=succeeded[0],
        publisher=urlparse(succeeded[0]).hostname or provider,
        text=_clip_text("\n\n".join(texts)),
        content_type="text/plain",
        credibility=credibility,
        validation_evidence=validation_evidence,
        metadata={"successful_urls": succeeded, "failed_fetches": failures},
    )


def _single_text_report(
    *,
    provider: str,
    category: SourceCategory,
    plan: MultiSourceResearchPlan,
    queries: tuple[str, ...],
    title: str,
    locator: str,
    publisher: str,
    text: str,
    content_type: str,
    credibility: CredibilityTier,
    validation_evidence: bool,
    metadata: dict[str, object] | None = None,
) -> ProviderResearchReport:
    text = _clip_text(text)
    if not text:
        return ProviderResearchReport(provider, category, ProviderState.NO_RESULTS, queries, blockers=("empty_content",))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    discovery_id = f"discovery:{category.value}:{_stable_hash(provider + locator)[:24]}"
    source_id = f"source:{category.value}:{_stable_hash(locator + digest)[:24]}"
    discovered = UnifiedDiscoveryResult(
        source_type=category,
        provider=provider,
        source_id=discovery_id,
        title=title,
        locator=locator,
        query=queries[0] if queries else "",
        research_topic=plan.research_topic,
        publisher=publisher,
        canonical_url=locator,
        content_url=locator,
        metadata=metadata or {},
        relevance=5,
        credibility=credibility,
        fixture_backed=False,
    )
    acquired = UnifiedAcquiredSource(
        source_id=source_id,
        source_type=category,
        provider=provider,
        final_url=locator,
        content_type=content_type,
        content_hash=digest,
        acquired_at=datetime.now(timezone.utc).isoformat(),
        byte_count=len(text.encode("utf-8")),
        normalization_status="normalized",
        fixture_backed=False,
        acquisition_state=AcquisitionState.CONTENT_ACQUIRED,
    )
    normalized = " ".join(text.lower().split())
    claim = UnifiedClaim(
        claim_id=f"claim:{category.value}:{_stable_hash(source_id + normalized)[:24]}",
        source_id=source_id,
        source_type=category,
        verbatim_text=text,
        normalized_claim=normalized,
        claim_topic=plan.research_topic,
        content_hash=digest,
        locator=locator,
        published_at=None,
        relevance_score=5,
        credibility_tier=credibility,
        stance=_stance(normalized),
        fixture_backed=False,
        idea_evidence=not validation_evidence,
        validation_evidence=validation_evidence,
        strategy_mutated=False,
        order_executed=False,
    )
    return ProviderResearchReport(
        provider,
        category,
        ProviderState.SUCCESS,
        queries,
        (discovered,),
        (acquired,),
        (claim,),
        fixture_backed=False,
    )


def _fetch_https(url: str, allowed_hosts: tuple[str, ...]) -> FetchResult:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    allowed = {item.strip().lower() for item in allowed_hosts if item.strip()}
    if parsed.scheme.lower() != "https":
        raise ValueError("https_required")
    if not hostname or hostname not in allowed:
        raise ValueError("host_not_allowed")
    if not _public_hostname(hostname):
        raise ValueError("private_or_local_host_blocked")

    request = Request(
        url,
        headers={
            "User-Agent": PRODUCTION_PROVIDER_USER_AGENT,
            "Accept": "text/html,application/json,application/rss+xml,application/xml,text/xml,application/zip,*/*;q=0.1",
        },
    )
    with urlopen(request, timeout=PRODUCTION_PROVIDER_TIMEOUT_SECONDS) as response:
        final_url = str(response.geturl())
        final = urlparse(final_url)
        final_host = (final.hostname or "").lower()
        if final.scheme.lower() != "https" or final_host not in allowed or not _public_hostname(final_host):
            raise ValueError("redirect_target_not_allowed")
        body = response.read(PRODUCTION_PROVIDER_MAX_RESPONSE_BYTES + 1)
        if len(body) > PRODUCTION_PROVIDER_MAX_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        content_type = str(response.headers.get_content_type() or "application/octet-stream").lower()
        return FetchResult(final_url=final_url, content_type=content_type, body=body)


def _text_from_payload(body: bytes, content_type: str) -> str:
    if "json" in content_type:
        obj = json.loads(body.decode("utf-8"))
        return _clip_text(json.dumps(obj, ensure_ascii=False, sort_keys=True))
    text = _decode_text(body)
    if "html" in content_type or "xml" in content_type:
        parser = _TextExtractor()
        parser.feed(text)
        text = " ".join(parser.parts)
    return _clip_text(text)


def _text_from_dart_zip(body: bytes) -> str:
    if not zipfile.is_zipfile(io.BytesIO(body)):
        return ""
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for name in archive.namelist()[:4]:
            if name.endswith("/"):
                continue
            raw = archive.read(name)
            text = _decode_text(raw)
            parser = _TextExtractor()
            parser.feed(text)
            extracted = " ".join(parser.parts)
            if extracted:
                parts.append(extracted)
            if sum(len(item) for item in parts) >= PRODUCTION_PROVIDER_MAX_TEXT_CHARS:
                break
    return _clip_text("\n".join(parts))


def _decode_text(body: bytes) -> str:
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def _clip_text(text: str) -> str:
    value = " ".join(text.split())
    return value[:PRODUCTION_PROVIDER_MAX_TEXT_CHARS]


def _stance(normalized: str) -> ClaimStance:
    negative = ("risk", "weak", "decline", "decrease", "uncertain", "uncertainty", "loss", "부진", "위험", "감소", "불확실")
    positive = ("growth", "increase", "improve", "profit", "recovery", "성장", "증가", "개선", "이익", "회복")
    has_negative = any(token in normalized for token in negative)
    has_positive = any(token in normalized for token in positive)
    if has_negative and has_positive:
        return ClaimStance.MIXED
    if has_negative:
        return ClaimStance.CONTRADICTING
    if has_positive:
        return ClaimStance.SUPPORTING
    return ClaimStance.INSUFFICIENT


def _dart_corp_code(symbol: str) -> str:
    env_key = f"GAON_DART_CORP_CODE_{symbol}"
    return os.environ.get(env_key, "").strip() or DART_CORP_CODES.get(symbol, "")


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.environ.get(name, "").split(",") if item.strip())


def _url_with_query(base: str, params: dict[str, str]) -> str:
    parsed = urlparse(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _redact_query(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query=""))


def _public_hostname(hostname: str) -> bool:
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    )


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _not_configured(
    provider: str,
    category: SourceCategory,
    queries: tuple[str, ...],
    reason: str,
) -> ProviderResearchReport:
    return ProviderResearchReport(
        provider,
        category,
        ProviderState.NOT_CONFIGURED,
        queries,
        blockers=(reason,),
        fixture_backed=False,
    )


def _provider_failure(
    provider: str,
    category: SourceCategory,
    queries: tuple[str, ...],
    reason: str,
) -> ProviderResearchReport:
    return ProviderResearchReport(
        provider,
        category,
        ProviderState.PROVIDER_FAILURE,
        queries,
        blockers=(reason,),
        fixture_backed=False,
    )

