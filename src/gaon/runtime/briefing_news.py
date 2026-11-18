"""장전 브리핑용 뉴스 수집 (읽기 전용).

공개 뉴스 RSS 헤드라인만 가져와 NewsIntelligenceItem 으로 정리한다. 주문·전략 변경·승격은 하지 않는다.
네트워크/파싱 실패는 빈 결과로 처리하고(브리핑은 그대로 발송된다) 예외를 밖으로 내보내지 않는다.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Callable

from gaon.knowledge.multi_source_research import MultiSourceResearchPlanner, SourceCategory
from gaon.knowledge.news_intelligence import NewsIntelligenceItem, derive_news_intelligence_items
from gaon.knowledge.production_external_providers import FetchCallable, ProductionNewsRssAdapter

LOG = logging.getLogger(__name__)

# 시장 전반 흐름 3가지: 국내 수급, 미국 마감, 환율·금리
PRE_MARKET_NEWS_QUERIES: tuple[str, ...] = (
    "코스피 증시 전망 외국인 기관 수급",
    "미국 증시 마감 나스닥 S&P500",
    "원달러 환율 금리 코스피",
)

NewsItemsProvider = Callable[[], "tuple[NewsIntelligenceItem, ...]"]


def collect_pre_market_news(
    observed_at: str,
    *,
    fetcher: FetchCallable | None = None,
    queries: tuple[str, ...] = PRE_MARKET_NEWS_QUERIES,
) -> tuple[NewsIntelligenceItem, ...]:
    planner = MultiSourceResearchPlanner()
    seen: set[str] = set()
    collected: list[NewsIntelligenceItem] = []
    for query in queries:
        try:
            plan = planner.build("pre-market news scan", symbol="KOSPI", company_name="KOSPI")
            plan = dataclasses.replace(plan, queries={**plan.queries, SourceCategory.NEWS.value: (query,)})
            report = ProductionNewsRssAdapter(symbol="KOSPI", fetcher=fetcher).research(plan)
            if not report.claims:
                continue
            for item in derive_news_intelligence_items(report, plan, observed_at=observed_at):
                key = " ".join(item.headline.lower().split())
                if key in seen:
                    continue
                seen.add(key)
                collected.append(item)
        except Exception:  # noqa: BLE001 - 뉴스는 보조 정보. 실패해도 브리핑은 나간다.
            LOG.warning("[briefing-news] query failed: %s", query, exc_info=True)
    return tuple(collected)
