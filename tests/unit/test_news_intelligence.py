from __future__ import annotations

import hashlib
import unittest

from gaon.knowledge.conflicts import ConflictStatus
from gaon.knowledge.multi_source_research import (
    ClaimStance,
    CredibilityTier,
    MultiSourceResearchPlan,
    MultiSourceResearchPolicy,
    ProviderResearchReport,
    ProviderState,
    SourceCategory,
    UnifiedClaim,
    UnifiedDiscoveryResult,
)
from gaon.knowledge.news_intelligence import (
    NewsResearchAction,
    decide_news_research_action,
    derive_news_intelligence_items,
    derive_news_intelligence_items_from_report_json,
    production_news_intelligence_release_check,
    production_safe_news_intelligence_items,
    render_news_intelligence_briefing,
)


def _plan() -> MultiSourceResearchPlan:
    return MultiSourceResearchPlan(
        plan_id="plan:test",
        research_topic="strategy.breakout.robustness",
        symbol="005930",
        strategy_family="breakout",
        providers=(SourceCategory.NEWS,),
        queries={SourceCategory.NEWS.value: ("Samsung Electronics semiconductor cycle volatility",)},
        policy=MultiSourceResearchPolicy(),
    )


def _report(text: str, *, fixture_backed: bool = False, category: SourceCategory = SourceCategory.NEWS) -> ProviderResearchReport:
    plan = _plan()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    discovered = UnifiedDiscoveryResult(
        source_type=category,
        provider="production:news:rss",
        source_id="discovery:news:test",
        title="005930 bounded news RSS",
        locator="https://news.google.com/rss/search?q=redacted",
        query=plan.queries[SourceCategory.NEWS.value][0],
        research_topic=plan.research_topic,
        publisher="Google News RSS",
        credibility=CredibilityTier.TIER_C_SECONDARY_INFORMATIONAL,
        fixture_backed=fixture_backed,
    )
    claim = UnifiedClaim(
        claim_id="claim:news:test",
        source_id="source:news:test",
        source_type=category,
        verbatim_text=text,
        normalized_claim=text.lower(),
        claim_topic=plan.research_topic,
        content_hash=digest,
        locator=discovered.locator,
        published_at=None,
        relevance_score=5,
        credibility_tier=CredibilityTier.TIER_C_SECONDARY_INFORMATIONAL,
        stance=ClaimStance.MIXED,
        fixture_backed=fixture_backed,
        idea_evidence=True,
        validation_evidence=False,
    )
    return ProviderResearchReport(
        provider="production:news:rss",
        category=category,
        state=ProviderState.SUCCESS,
        queries=plan.queries[SourceCategory.NEWS.value],
        discovered=(discovered,),
        acquired=(),
        claims=(claim,),
        fixture_backed=fixture_backed,
    )


class NewsIntelligenceTests(unittest.TestCase):
    def test_splits_combined_rss_text_into_one_item_per_headline(self) -> None:
        text = (
            "Samsung chip demand improves | publisher=Real Wire | published=Fri, 14 Aug 2026 10:00:00 GMT\n"
            "Memory pricing risk remains | publisher=Market Desk | published=Fri, 14 Aug 2026 11:00:00 GMT"
        )
        items = derive_news_intelligence_items(_report(text), _plan(), observed_at="2026-08-16T09:00:00+09:00")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].headline, "Samsung chip demand improves")
        self.assertEqual(items[0].source, "Real Wire")
        self.assertEqual(items[1].headline, "Memory pricing risk remains")

    def test_contract_fields_present_and_bounded(self) -> None:
        text = "Samsung chip demand improves | publisher=Real Wire | published=Fri, 14 Aug 2026 10:00:00 GMT"
        item = derive_news_intelligence_items(_report(text), _plan(), observed_at="2026-08-16T09:00:00+09:00")[0]
        payload = item.to_json()
        for field in (
            "headline", "source", "published_at", "provider", "locator", "content_hash",
            "importance_score", "affected_markets", "affected_symbols", "affected_sectors",
            "impact", "strategy_relevant", "hypothesis_conflict", "research_action",
        ):
            self.assertIn(field, payload)
        self.assertTrue(0 <= payload["importance_score"] <= 100)
        self.assertIn(payload["impact"], {"positive", "negative", "mixed", "uncertain"})

    def test_impact_reuses_existing_keyword_stance_classifier(self) -> None:
        positive = "Samsung earnings growth accelerates | publisher=Wire | published=unknown"
        negative = "Samsung faces demand decline risk | publisher=Wire | published=unknown"
        pos_item = derive_news_intelligence_items(_report(positive), _plan(), observed_at="t")[0]
        neg_item = derive_news_intelligence_items(_report(negative), _plan(), observed_at="t")[0]
        self.assertEqual(pos_item.impact.value, "positive")
        self.assertEqual(neg_item.impact.value, "negative")

    def test_hypothesis_conflict_pass_through_forces_counter_hypothesis_action(self) -> None:
        text = "Samsung chip demand improves | publisher=Wire | published=unknown"
        item = derive_news_intelligence_items(
            _report(text), _plan(), observed_at="t", conflict=ConflictStatus.UNRESOLVED_CONFLICT
        )[0]
        self.assertEqual(item.hypothesis_conflict, "unresolved_conflict")
        self.assertEqual(item.research_action, "test_counter_hypothesis")

    def test_no_conflict_supplied_is_labelled_not_evaluated(self) -> None:
        text = "Samsung chip demand improves | publisher=Wire | published=unknown"
        item = derive_news_intelligence_items(_report(text), _plan(), observed_at="t")[0]
        self.assertEqual(item.hypothesis_conflict, "not_evaluated")

    def test_fixture_backed_evidence_is_excluded_from_production_safe_view(self) -> None:
        text = "Samsung chip demand improves | publisher=Wire | published=unknown"
        fixture_items = derive_news_intelligence_items(
            _report(text, fixture_backed=True), _plan(), observed_at="t"
        )
        self.assertTrue(fixture_items)
        self.assertFalse(any(item.production_safe for item in fixture_items))
        self.assertEqual(production_safe_news_intelligence_items(fixture_items), ())

    def test_real_evidence_is_production_safe(self) -> None:
        text = "Samsung chip demand improves | publisher=Wire | published=unknown"
        items = derive_news_intelligence_items(_report(text, fixture_backed=False), _plan(), observed_at="t")
        self.assertEqual(production_safe_news_intelligence_items(items), items)

    def test_non_news_category_report_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            derive_news_intelligence_items(_report("x", category=SourceCategory.WEB), _plan(), observed_at="t")

    def test_korean_briefing_renders_action_and_conflict_note(self) -> None:
        text = "Samsung chip demand improves | publisher=Wire | published=unknown"
        items = derive_news_intelligence_items(
            _report(text), _plan(), observed_at="t", conflict=ConflictStatus.UNRESOLVED_CONFLICT
        )
        briefing = render_news_intelligence_briefing(items)
        self.assertIn("[뉴스 인텔리전스]", briefing)
        self.assertIn("충돌하여 재검증이 필요합니다", briefing)

    def test_empty_briefing_is_honest_about_no_evidence(self) -> None:
        self.assertEqual(render_news_intelligence_briefing(()), "새로 반영할 만한 뉴스 근거가 없습니다.")

    def test_release_check_passes(self) -> None:
        payload = production_news_intelligence_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertGreater(payload["items"], 0)


def _news_report_json(text: str, *, fixture_backed: bool = False) -> dict:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "provider": "production:news:rss",
        "category": "news",
        "state": "success",
        "fixture_backed": fixture_backed,
        "claims": [
            {
                "source_id": "s1",
                "locator": "https://news.google.com/rss/search?q=redacted",
                "content_hash": digest,
                "published_at": None,
                "fixture_backed": fixture_backed,
                "verbatim_text": text,
            }
        ],
    }


class DeriveFromReportJsonTests(unittest.TestCase):
    """gaon.knowledge.telegram_autonomous_learning._news_intelligence_summary
    passes the real ProviderResearchReport.to_json() shape (as produced by
    the real ProductionNewsRssAdapter inside
    _run_production_multi_source_research) straight in - this is the JSON
    entrypoint that path actually uses."""

    def test_extracts_items_from_provider_report_json(self) -> None:
        text = "Samsung chip demand improves | publisher=Real Wire | published=Fri, 14 Aug 2026 10:00:00 GMT"
        items = derive_news_intelligence_items_from_report_json(
            _news_report_json(text), symbol="005930", queries=("Samsung Electronics",), observed_at="2026-08-16T09:00:00Z"
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].headline, "Samsung chip demand improves")
        self.assertEqual(items[0].source, "Real Wire")
        self.assertFalse(items[0].fixture_backed)

    def test_rejects_non_news_category(self) -> None:
        report = _news_report_json("x")
        report["category"] = "web"
        with self.assertRaises(ValueError):
            derive_news_intelligence_items_from_report_json(report, symbol="005930", queries=(), observed_at="t")

    def test_fixture_backed_report_marks_items_fixture_backed(self) -> None:
        items = derive_news_intelligence_items_from_report_json(
            _news_report_json("Samsung chip demand improves | publisher=Wire | published=unknown", fixture_backed=True),
            symbol="005930",
            queries=(),
            observed_at="t",
        )
        self.assertTrue(items[0].fixture_backed)
        self.assertEqual(production_safe_news_intelligence_items(items), ())


class DecideNewsResearchActionTests(unittest.TestCase):
    def _item(self, headline: str, *, hypothesis_conflict: str = "not_evaluated", strategy_relevant: bool = False):
        items = derive_news_intelligence_items_from_report_json(
            _news_report_json(f"{headline} | publisher=Wire | published=unknown"),
            symbol="005930",
            queries=("Samsung Electronics semiconductor",) if strategy_relevant else (),
            observed_at="t",
            conflict=None
            if hypothesis_conflict == "not_evaluated"
            else ConflictStatus.UNRESOLVED_CONFLICT,
        )
        return items[0]

    def test_irrelevant_headline_is_ignored(self) -> None:
        item = self._item("Local weather forecast improves this weekend")
        self.assertEqual(decide_news_research_action(item, active_symbol="005930"), NewsResearchAction.IGNORE)

    def test_explicit_symbol_mention_without_a_strong_signal_is_monitored(self) -> None:
        item = self._item("005930 to hold annual shareholder meeting next week")
        self.assertEqual(decide_news_research_action(item, active_symbol="005930"), NewsResearchAction.MONITOR)

    def test_explicit_symbol_mention_with_high_importance_escalates_to_revalidate(self) -> None:
        item = self._item("005930 shares trade higher on demand recovery")
        self.assertEqual(decide_news_research_action(item, active_symbol="005930"), NewsResearchAction.REVALIDATE)

    def test_unresolved_hypothesis_conflict_starts_counter_hypothesis(self) -> None:
        item = self._item("Samsung demand outlook unchanged", hypothesis_conflict="unresolved_conflict")
        self.assertEqual(item.hypothesis_conflict, "unresolved_conflict")
        self.assertEqual(
            decide_news_research_action(item, active_symbol="005930"), NewsResearchAction.START_COUNTER_HYPOTHESIS
        )

    def test_trading_halt_liquidity_signal_triggers_revalidate(self) -> None:
        item = self._item("Samsung faces trading halt amid liquidity crunch")
        self.assertEqual(decide_news_research_action(item, active_symbol="005930"), NewsResearchAction.REVALIDATE)

    def test_market_wide_structural_event_triggers_revalidate(self) -> None:
        item = self._item("Regulation shakes up market-wide trading rules")
        self.assertEqual(decide_news_research_action(item, active_symbol="005930"), NewsResearchAction.REVALIDATE)

    def test_macro_regime_signal_without_high_importance_is_monitored(self) -> None:
        item = self._item("Federal Reserve signals rate hike path unchanged")
        self.assertEqual(decide_news_research_action(item, active_symbol="005930"), NewsResearchAction.MONITOR)

    def test_weakly_query_relevant_headline_is_remembered_not_escalated(self) -> None:
        item = self._item("Samsung factory tour draws local visitors", strategy_relevant=True)
        action = decide_news_research_action(item, active_symbol=None)
        self.assertIn(action, (NewsResearchAction.REMEMBER, NewsResearchAction.MONITOR))

    def test_fetch_alone_never_implies_escalation_without_a_relevance_signal(self) -> None:
        # Being fetched at all must never be sufficient; only an explicit
        # relevance signal (symbol/macro/cost-liquidity/market-wide/conflict)
        # may escalate past ignore.
        item = self._item("Unrelated celebrity gossip roundup")
        self.assertEqual(decide_news_research_action(item, active_symbol="005930"), NewsResearchAction.IGNORE)


if __name__ == "__main__":
    unittest.main()
