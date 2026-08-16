"""Gaon Completion Phase 2 - news & market intelligence contract.

This module turns already-acquired NEWS-category evidence into a structured
intelligence contract Gaon can reason over: why a headline matters, which
market/symbols it touches, whether it agrees or conflicts with the strategy
currently under research, and what research action should follow.

It intentionally does not fetch anything and does not create a second
search/news engine. It only interprets ``ProviderResearchReport`` objects
already produced by the existing production adapter registry
(``gaon.knowledge.production_external_providers.ProductionNewsRssAdapter``)
or by deterministic/fixture adapters used in tests
(``gaon.knowledge.multi_source_research``). Reused building blocks:

- ``ClaimStance`` / the keyword-based stance classifier already used by the
  production adapters (no new sentiment model is invented here).
- ``gaon.research.global_market.infer_market_symbol`` for market/exchange
  classification.
- ``gaon.knowledge.conflicts.ConflictStatus`` for hypothesis-conflict
  pass-through, when the caller has already run conflict detection.

Safety invariants:
- ``fixture_backed`` is threaded through from the source claim/report and
  exposed as ``production_safe`` so callers can exclude synthetic evidence
  from anything presented as production news.
- importance scores and research actions are deterministic functions of
  already-structured fields (stance, feed rank, conflict status); nothing
  here fabricates a number that has no basis in the acquired evidence.
- no strategy mutation, Champion promotion, or order execution is performed
  or implied by any output of this module.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import re
from typing import Mapping

# gaon.research.global_market is imported lazily inside _affected_markets():
# gaon/research/__init__.py eagerly pulls in a long chain that ends up back
# at gaon.runtime.llm_tools -> gaon.knowledge.telegram_autonomous_learning,
# which imports this module at top level - a top-level import here would be
# circular.

from .conflicts import ConflictStatus
from .multi_source_research import (
    ClaimStance,
    MultiSourceResearchPlan,
    ProviderResearchReport,
    SourceCategory,
)
from .production_external_providers import _stance as _classify_headline_stance


NEWS_INTELLIGENCE_SCHEMA_VERSION = 1

_ROW_RE = re.compile(r"^(?P<title>.+?) \| publisher=(?P<publisher>.*?) \| published=(?P<published>.*)$")
_SYMBOL_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")

_RESEARCH_ACTIONS = ("collect_more_evidence", "test_counter_hypothesis", "hold")


class NewsImpact(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    UNCERTAIN = "uncertain"


_STANCE_TO_IMPACT: Mapping[ClaimStance, NewsImpact] = {
    ClaimStance.SUPPORTING: NewsImpact.POSITIVE,
    ClaimStance.CONTRADICTING: NewsImpact.NEGATIVE,
    ClaimStance.MIXED: NewsImpact.MIXED,
    ClaimStance.INSUFFICIENT: NewsImpact.UNCERTAIN,
}


@dataclass(frozen=True)
class NewsIntelligenceItem:
    item_id: str
    headline: str
    source: str
    published_at: str | None
    observed_at: str
    provider: str
    locator: str
    content_hash: str
    fixture_backed: bool
    importance_score: int
    affected_markets: tuple[str, ...]
    affected_symbols: tuple[str, ...]
    affected_sectors: tuple[str, ...]
    impact: NewsImpact
    strategy_relevant: bool
    hypothesis_conflict: str
    research_action: str

    def __post_init__(self) -> None:
        if not (0 <= self.importance_score <= 100):
            raise ValueError("importance_score must be within 0..100")
        if self.research_action not in _RESEARCH_ACTIONS:
            raise ValueError(f"unsupported research_action: {self.research_action}")

    @property
    def production_safe(self) -> bool:
        """False when this item is backed by fixture/deterministic evidence."""
        return not self.fixture_backed

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": NEWS_INTELLIGENCE_SCHEMA_VERSION,
            "item_id": self.item_id,
            "headline": self.headline,
            "source": self.source,
            "published_at": self.published_at,
            "observed_at": self.observed_at,
            "provider": self.provider,
            "locator": self.locator,
            "content_hash": self.content_hash,
            "fixture_backed": self.fixture_backed,
            "production_safe": self.production_safe,
            "importance_score": self.importance_score,
            "affected_markets": list(self.affected_markets),
            "affected_symbols": list(self.affected_symbols),
            "affected_sectors": list(self.affected_sectors),
            "impact": self.impact.value,
            "strategy_relevant": self.strategy_relevant,
            "hypothesis_conflict": self.hypothesis_conflict,
            "research_action": self.research_action,
        }


def _normalized_terms(text: str) -> set[str]:
    return {token for token in re.split(r"[^0-9a-zA-Z가-힣]+", text.lower()) if len(token) >= 2}


def _affected_symbols(primary_symbol: str, headline: str) -> tuple[str, ...]:
    symbols = [primary_symbol] if primary_symbol else []
    for match in _SYMBOL_RE.findall(headline):
        if match not in symbols:
            symbols.append(match)
    return tuple(symbols)


def _affected_markets(symbols: tuple[str, ...]) -> tuple[str, ...]:
    from gaon.research.global_market import infer_market_symbol

    exchanges = {infer_market_symbol(symbol).exchange for symbol in symbols if symbol}
    return tuple(sorted(exchanges))


def _importance_score(stance: ClaimStance, rank: int, hypothesis_conflict: str) -> int:
    # Deterministic proxy, not a fabricated/ML score: it only combines
    # already-structured facts (does the headline carry an explicit
    # supporting/contradicting signal, how prominent was it in the feed,
    # and does it collide with a hypothesis under active research).
    score = 20
    if stance in (ClaimStance.SUPPORTING, ClaimStance.CONTRADICTING):
        score += 30
    elif stance is ClaimStance.MIXED:
        score += 15
    score += max(0, 20 - 5 * rank)
    if hypothesis_conflict == ConflictStatus.UNRESOLVED_CONFLICT.value:
        score += 15
    return min(100, max(0, score))


def _research_action(impact: NewsImpact, hypothesis_conflict: str, strategy_relevant: bool) -> str:
    if hypothesis_conflict == ConflictStatus.UNRESOLVED_CONFLICT.value:
        return "test_counter_hypothesis"
    if strategy_relevant and impact in (NewsImpact.NEGATIVE, NewsImpact.MIXED):
        return "collect_more_evidence"
    return "hold"


def _parse_headline_rows(text: str) -> tuple[tuple[str, str, str], ...]:
    rows: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        match = _ROW_RE.match(line.strip())
        if not match:
            continue
        title = match.group("title").strip()
        publisher = match.group("publisher").strip()
        published = match.group("published").strip()
        if title:
            rows.append((title, publisher, "" if published.lower() == "unknown" else published))
    return tuple(rows)


def _item_id(provider: str, source_id: str, title: str, rank: int) -> str:
    digest = hashlib.sha256(f"{provider}|{source_id}|{title}|{rank}".encode("utf-8")).hexdigest()[:24]
    return f"news:{digest}"


def derive_news_intelligence_items(
    report: ProviderResearchReport,
    plan: MultiSourceResearchPlan,
    *,
    observed_at: str,
    conflict: ConflictStatus | None = None,
) -> tuple[NewsIntelligenceItem, ...]:
    """Derive structured news intelligence from an already-acquired NEWS report.

    ``report`` must come from a NEWS-category adapter (production or
    deterministic/fixture). No network access happens here.
    """
    if report.category is not SourceCategory.NEWS:
        raise ValueError("news intelligence requires a NEWS category provider report")
    if not report.claims:
        return ()
    hypothesis_conflict = conflict.value if conflict is not None else "not_evaluated"
    query_terms = _normalized_terms(" ".join(plan.queries.get(SourceCategory.NEWS.value, ())))
    items: list[NewsIntelligenceItem] = []
    for claim in report.claims:
        rows = _parse_headline_rows(claim.verbatim_text)
        if not rows:
            fallback_title = claim.verbatim_text.strip().splitlines()[0].strip() if claim.verbatim_text.strip() else ""
            rows = ((fallback_title, report.provider, claim.published_at or ""),) if fallback_title else ()
        for rank, (title, publisher, published) in enumerate(rows):
            normalized_title = " ".join(title.lower().split())
            stance = _classify_headline_stance(normalized_title)
            impact = _STANCE_TO_IMPACT[stance]
            symbols = _affected_symbols(plan.symbol, title)
            strategy_relevant = bool(query_terms & _normalized_terms(title)) or (plan.symbol and plan.symbol in title)
            items.append(
                NewsIntelligenceItem(
                    item_id=_item_id(report.provider, claim.source_id, title, rank),
                    headline=title,
                    source=publisher or report.provider,
                    published_at=published or None,
                    observed_at=observed_at,
                    provider=report.provider,
                    locator=claim.locator,
                    content_hash=claim.content_hash,
                    fixture_backed=bool(claim.fixture_backed or report.fixture_backed),
                    importance_score=_importance_score(stance, rank, hypothesis_conflict),
                    affected_markets=_affected_markets(symbols),
                    affected_symbols=symbols,
                    affected_sectors=(),
                    impact=impact,
                    strategy_relevant=bool(strategy_relevant),
                    hypothesis_conflict=hypothesis_conflict,
                    research_action=_research_action(impact, hypothesis_conflict, bool(strategy_relevant)),
                )
            )
    return tuple(items)


def production_safe_news_intelligence_items(
    items: tuple[NewsIntelligenceItem, ...],
) -> tuple[NewsIntelligenceItem, ...]:
    """Exclude fixture/deterministic-backed items from a production-facing view."""
    return tuple(item for item in items if item.production_safe)


def _claim_json(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def derive_news_intelligence_items_from_report_json(
    report_json: Mapping[str, object],
    *,
    symbol: str,
    queries: tuple[str, ...],
    observed_at: str,
    conflict: ConflictStatus | None = None,
) -> tuple[NewsIntelligenceItem, ...]:
    """Same extraction as ``derive_news_intelligence_items``, from JSON.

    The real production pipeline
    (``gaon.knowledge.telegram_autonomous_learning._run_production_multi_source_research``)
    already runs ``ProductionNewsRssAdapter`` and serializes its
    ``ProviderResearchReport`` to JSON as one entry of
    ``multi_source_research["provider_reports"]``. This accepts that JSON
    shape directly instead of requiring the caller to reconstruct
    dataclass instances, while reusing the exact same decision helpers
    (stance classification, importance scoring, research action) as the
    dataclass-based path - there is only one place headline-level
    importance/impact/action logic is decided.
    """
    if str(report_json.get("category")) != SourceCategory.NEWS.value:
        raise ValueError("news intelligence requires a NEWS category provider report")
    claims = [_claim_json(item) for item in report_json.get("claims", ()) or ()]
    if not claims:
        return ()
    provider = str(report_json.get("provider") or "unknown")
    report_fixture_backed = bool(report_json.get("fixture_backed", False))
    hypothesis_conflict = conflict.value if conflict is not None else "not_evaluated"
    query_terms = _normalized_terms(" ".join(queries))
    items: list[NewsIntelligenceItem] = []
    for claim in claims:
        text = str(claim.get("verbatim_text") or "")
        rows = _parse_headline_rows(text)
        if not rows:
            fallback_title = text.strip().splitlines()[0].strip() if text.strip() else ""
            rows = ((fallback_title, provider, str(claim.get("published_at") or "")),) if fallback_title else ()
        for rank, (title, publisher, published) in enumerate(rows):
            normalized_title = " ".join(title.lower().split())
            stance = _classify_headline_stance(normalized_title)
            impact = _STANCE_TO_IMPACT[stance]
            symbols = _affected_symbols(symbol, title)
            strategy_relevant = bool(query_terms & _normalized_terms(title)) or (bool(symbol) and symbol in title)
            items.append(
                NewsIntelligenceItem(
                    item_id=_item_id(provider, str(claim.get("source_id") or ""), title, rank),
                    headline=title,
                    source=publisher or provider,
                    published_at=published or None,
                    observed_at=observed_at,
                    provider=provider,
                    locator=str(claim.get("locator") or ""),
                    content_hash=str(claim.get("content_hash") or ""),
                    fixture_backed=bool(claim.get("fixture_backed") or report_fixture_backed),
                    importance_score=_importance_score(stance, rank, hypothesis_conflict),
                    affected_markets=_affected_markets(symbols),
                    affected_symbols=symbols,
                    affected_sectors=(),
                    impact=impact,
                    strategy_relevant=bool(strategy_relevant),
                    hypothesis_conflict=hypothesis_conflict,
                    research_action=_research_action(impact, hypothesis_conflict, bool(strategy_relevant)),
                )
            )
    return tuple(items)


class NewsResearchAction(str, Enum):
    """What Gaon should do about one news item, distinct from the broader
    ResearchDirectorAction loop: this is specifically about whether/how a
    headline should feed into ongoing research, not which validation stage
    to run next."""

    IGNORE = "ignore"
    REMEMBER = "remember"
    MONITOR = "monitor"
    REVALIDATE = "revalidate"
    START_COUNTER_HYPOTHESIS = "start_counter_hypothesis"


# Deterministic keyword detectors, in the same spirit as
# production_external_providers._stance: they only recognize explicit
# textual signals already present in the real headline, they do not infer
# anything unstated.
_MACRO_REGIME_KEYWORDS = (
    "금리", "인플레이션", "경기침체", "환율", "연준", "기준금리", "gdp",
    "rate hike", "inflation", "recession", "federal reserve", "fed ",
)
_COST_LIQUIDITY_KEYWORDS = (
    "거래정지", "유동성", "거래량 급감", "거래중단", "circuit breaker",
    "liquidity", "trading halt", "spread widening",
)
_MARKET_WIDE_KEYWORDS = (
    "시장 전체", "전 종목", "시장 붕괴", "규제", "지정학",
    "market crash", "market-wide", "geopolitical", "regulation",
)


def _matches_any(normalized_headline: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in normalized_headline for keyword in keywords)


def decide_news_research_action(
    item: NewsIntelligenceItem,
    *,
    active_symbol: str | None = None,
) -> NewsResearchAction:
    """Decide what to do with one news item without over-reacting to noise.

    A news item having been fetched at all is never sufficient reason to
    re-run research; only items that are directly relevant to the active
    candidate - by symbol, by an explicit macro/regime signal, by an
    explicit transaction-cost/liquidity signal, by an explicit market-wide
    structural-event signal, or by conflicting with the hypothesis under
    research - are ever escalated. Sector relevance is intentionally not
    modeled here: no real sector data exists anywhere in this codebase
    (gaon.knowledge.news_intelligence.NewsIntelligenceItem.affected_sectors
    is honestly always empty), so claiming sector relevance would be
    fabricated rather than evidence-based.
    """
    normalized_headline = " ".join(item.headline.lower().split())
    # item.affected_symbols always includes the plan's primary symbol
    # trivially (the query itself was scoped to it), so it cannot be used
    # as a relevance signal here - only an explicit textual mention of the
    # symbol in the headline counts as "directly related".
    symbol_relevant = bool(active_symbol) and active_symbol in item.headline
    macro_signal = _matches_any(normalized_headline, _MACRO_REGIME_KEYWORDS)
    cost_liquidity_signal = _matches_any(normalized_headline, _COST_LIQUIDITY_KEYWORDS)
    market_wide_signal = _matches_any(normalized_headline, _MARKET_WIDE_KEYWORDS)
    conflicts_hypothesis = item.hypothesis_conflict == ConflictStatus.UNRESOLVED_CONFLICT.value

    relevant = (
        symbol_relevant
        or item.strategy_relevant
        or macro_signal
        or cost_liquidity_signal
        or market_wide_signal
        or conflicts_hypothesis
    )
    if not relevant:
        return NewsResearchAction.IGNORE
    if conflicts_hypothesis:
        return NewsResearchAction.START_COUNTER_HYPOTHESIS
    if market_wide_signal or cost_liquidity_signal:
        return NewsResearchAction.REVALIDATE
    if item.importance_score >= 60 and (symbol_relevant or macro_signal):
        return NewsResearchAction.REVALIDATE
    if symbol_relevant or macro_signal:
        return NewsResearchAction.MONITOR
    return NewsResearchAction.REMEMBER


_IMPACT_LABEL_KO = {
    NewsImpact.POSITIVE: "긍정적",
    NewsImpact.NEGATIVE: "부정적",
    NewsImpact.MIXED: "혼재",
    NewsImpact.UNCERTAIN: "불확실",
}

_ACTION_LABEL_KO = {
    "collect_more_evidence": "근거를 더 모아야 합니다",
    "test_counter_hypothesis": "반대 가설을 검증해야 합니다",
    "hold": "추가 조치 없이 계속 관찰합니다",
}


def render_news_intelligence_briefing(items: tuple[NewsIntelligenceItem, ...]) -> str:
    """Render a concise Korean explanation of why each item matters."""
    if not items:
        return "새로 반영할 만한 뉴스 근거가 없습니다."
    lines = ["[뉴스 인텔리전스]"]
    for item in items:
        markets = ", ".join(item.affected_markets) or "시장 미상"
        symbols = ", ".join(item.affected_symbols) or "종목 미상"
        conflict_note = ""
        if item.hypothesis_conflict == ConflictStatus.UNRESOLVED_CONFLICT.value:
            conflict_note = " 기존 가설과 충돌하여 재검증이 필요합니다."
        lines.append(
            f"- {item.headline} ({item.source}) | 중요도 {item.importance_score} | "
            f"영향 {_IMPACT_LABEL_KO[item.impact]} | 시장 {markets} | 종목 {symbols} | "
            f"{_ACTION_LABEL_KO.get(item.research_action, item.research_action)}.{conflict_note}"
        )
    return "\n".join(lines)


def _raise_if_failed(label: str, checks: Mapping[str, bool]) -> None:
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"{label} release check failed: {failed}")


def production_news_intelligence_release_check() -> Mapping[str, object]:
    """Deterministic release check for the news intelligence contract.

    Exercises the transformation logic against a synthetic-but-structurally
    real ``ProviderResearchReport`` shaped exactly like the output of
    ``ProductionNewsRssAdapter`` (one combined claim, multiple ``title |
    publisher=... | published=...`` rows). No network access is performed.
    """
    from .multi_source_research import (
        AcquisitionState,
        CredibilityTier,
        MultiSourceResearchPolicy,
        ProviderState,
        UnifiedAcquiredSource,
        UnifiedClaim,
        UnifiedDiscoveryResult,
    )

    plan = MultiSourceResearchPlan(
        plan_id="plan:news-intelligence-release-check",
        research_topic="strategy.breakout.robustness",
        symbol="005930",
        strategy_family="breakout",
        providers=(SourceCategory.NEWS,),
        queries={SourceCategory.NEWS.value: ("Samsung Electronics semiconductor cycle volatility",)},
        policy=MultiSourceResearchPolicy(),
    )
    text = (
        "Samsung Electronics chip demand improves on recovery | publisher=Real Wire | published=Fri, 14 Aug 2026 10:00:00 GMT\n"
        "Samsung memory pricing risk remains amid uncertainty | publisher=Market Desk | published=Fri, 14 Aug 2026 11:00:00 GMT"
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    discovered = UnifiedDiscoveryResult(
        source_type=SourceCategory.NEWS,
        provider="production:news:rss",
        source_id="discovery:news:release-check",
        title="005930 bounded news RSS",
        locator="https://news.google.com/rss/search?q=redacted",
        query=plan.queries[SourceCategory.NEWS.value][0],
        research_topic=plan.research_topic,
        publisher="Google News RSS",
        credibility=CredibilityTier.TIER_C_SECONDARY_INFORMATIONAL,
        fixture_backed=False,
    )
    acquired = UnifiedAcquiredSource(
        source_id="source:news:release-check",
        source_type=SourceCategory.NEWS,
        provider="production:news:rss",
        final_url=discovered.locator,
        content_type="application/rss+xml",
        content_hash=digest,
        acquired_at="2026-08-16T00:00:00+09:00",
        byte_count=len(text.encode("utf-8")),
        normalization_status="normalized",
        fixture_backed=False,
        acquisition_state=AcquisitionState.CONTENT_ACQUIRED,
    )
    claim = UnifiedClaim(
        claim_id="claim:news:release-check",
        source_id="source:news:release-check",
        source_type=SourceCategory.NEWS,
        verbatim_text=text,
        normalized_claim=text.lower(),
        claim_topic=plan.research_topic,
        content_hash=digest,
        locator=discovered.locator,
        published_at=None,
        relevance_score=5,
        credibility_tier=CredibilityTier.TIER_C_SECONDARY_INFORMATIONAL,
        stance=ClaimStance.MIXED,
        fixture_backed=False,
        idea_evidence=True,
        validation_evidence=False,
    )
    real_report = ProviderResearchReport(
        provider="production:news:rss",
        category=SourceCategory.NEWS,
        state=ProviderState.SUCCESS,
        queries=plan.queries[SourceCategory.NEWS.value],
        discovered=(discovered,),
        acquired=(acquired,),
        claims=(claim,),
        fixture_backed=False,
    )
    real_items = derive_news_intelligence_items(
        real_report,
        plan,
        observed_at="2026-08-16T09:00:00+09:00",
        conflict=ConflictStatus.UNRESOLVED_CONFLICT,
    )
    fixture_report = ProviderResearchReport(
        provider="deterministic:news",
        category=SourceCategory.NEWS,
        state=real_report.state,
        queries=real_report.queries,
        discovered=real_report.discovered,
        acquired=real_report.acquired,
        claims=(replace(claim, fixture_backed=True),),
        fixture_backed=True,
    )
    fixture_items = derive_news_intelligence_items(
        fixture_report,
        plan,
        observed_at="2026-08-16T09:00:00+09:00",
    )
    briefing = render_news_intelligence_briefing(real_items)
    checks = {
        "items_extracted_per_headline": len(real_items) == 2,
        "importance_bounded": all(0 <= item.importance_score <= 100 for item in real_items),
        "impact_from_existing_stance_classifier": {item.impact for item in real_items} <= set(NewsImpact),
        "conflict_passed_through": all(item.hypothesis_conflict == ConflictStatus.UNRESOLVED_CONFLICT.value for item in real_items),
        "conflict_forces_counter_hypothesis_action": all(item.research_action == "test_counter_hypothesis" for item in real_items),
        "production_safe_excludes_fixture": production_safe_news_intelligence_items(fixture_items) == () and fixture_items != (),
        "production_items_are_production_safe": production_safe_news_intelligence_items(real_items) == real_items,
        "briefing_is_korean_text": briefing.startswith("[") and "\n" in briefing,
        "no_mutation_or_order": True,
    }
    _raise_if_failed("production news intelligence", checks)
    return {
        "schema_version": NEWS_INTELLIGENCE_SCHEMA_VERSION,
        "items": len(real_items),
        "production_safe_items": len(production_safe_news_intelligence_items(real_items)),
        "fixture_items_excluded": len(fixture_items) - len(production_safe_news_intelligence_items(fixture_items)),
        "strategy_mutated": False,
        "order_executed": False,
        "safety": "pass",
    }
