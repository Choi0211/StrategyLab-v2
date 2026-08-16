"""Gaon Final Integration Program - Step 2 integration acceptance.

Proves that important news, when it is registered as evidence at all, is
attached to the REAL Autonomous Learning V2 payload
(gaon.knowledge.telegram_autonomous_learning) with provenance/timestamp
preserved, and that the news-driven action vocabulary
(ignore/remember/monitor/revalidate/start_counter_hypothesis) is only ever
escalated for news that actually satisfies a real relevance condition -
never merely because a headline was fetched.
"""

from __future__ import annotations

import hashlib
import unittest

from gaon.knowledge.telegram_autonomous_learning import production_autonomous_learning_payload_from_baseline


def _baseline(*, trades: int, symbols: int) -> dict[str, object]:
    strategy = {"strategy_id": "baseline", "fingerprint": "fp:baseline", "rules": ["breakout"]}
    candidate_strategy = {"strategy_id": "candidate", "fingerprint": "fp:candidate", "rules": ["breakout", "volume"]}
    return {
        "dataset": {
            "metadata": {
                "source": "real:yahoo-chart",
                "fixture_backed": False,
                "rows": 1222,
                "start_date": "2021-07-25",
                "end_date": "2026-07-24",
            }
        },
        "quality": {"status": "pass", "blocking_findings": []},
        "strategy": strategy,
        "validation": {"symbols": symbols, "warmup_bars": 60, "entry_opportunities": 120, "signals": 50},
        "backtest": {"source": "real", "metrics": {"trade_count": trades, "total_return": 0.12, "mdd": 0.08}},
        "candidates": [
            {
                "candidate_id": "candidate:volume",
                "strategy": candidate_strategy,
                "backtest_result": {
                    "result_id": "backtest:candidate",
                    "source": "real",
                    "strategy": candidate_strategy,
                    "metrics": {"trade_count": trades, "total_return": 0.13, "mdd": 0.07, "profit_factor": 1.4},
                },
            }
        ],
    }


def _news_report(text: str, *, fixture_backed: bool = False) -> dict[str, object]:
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
                "published_at": "Fri, 14 Aug 2026 10:00:00 GMT",
                "fixture_backed": fixture_backed,
                "verbatim_text": text,
            }
        ],
    }


class NewsResearchIntegrationTests(unittest.TestCase):
    def test_no_news_evidence_is_honestly_empty_not_fabricated(self) -> None:
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=45, symbols=5),
            external_research={"state": "content_unavailable"},
        )
        news = payload["autonomous_learning_v2"]["news_intelligence"]
        self.assertEqual(news["items"], [])
        self.assertEqual(news["actions_summary"], {})

    def test_relevant_news_is_registered_as_evidence_with_provenance_and_timestamp(self) -> None:
        external_research = {
            "state": "content_unavailable",
            "multi_source_research": {
                "provider_reports": [
                    _news_report("Samsung faces trading halt amid liquidity crunch | publisher=Wire | published=Fri, 14 Aug 2026 10:00:00 GMT")
                ],
                "research_plan": {"queries": {"news": ["Samsung Electronics semiconductor cycle"]}},
                "evidence_bundle": {"evidence_strength": "exploratory", "conflict_status": "insufficient"},
            },
        }
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=45, symbols=5),
            external_research=external_research,
        )
        news = payload["autonomous_learning_v2"]["news_intelligence"]
        self.assertEqual(len(news["items"]), 1)
        item = news["items"][0]
        # Provenance and timestamp are preserved end to end.
        self.assertTrue(item["locator"])
        self.assertTrue(item["content_hash"])
        self.assertTrue(item["observed_at"])
        self.assertEqual(item["published_at"], "Fri, 14 Aug 2026 10:00:00 GMT")
        self.assertEqual(item["provider"], "production:news:rss")
        # A liquidity/trading-halt signal is a real relevance condition.
        self.assertEqual(item["news_research_action"], "revalidate")
        self.assertEqual(news["actions_summary"], {"revalidate": 1})

    def test_irrelevant_news_never_escalates_research_just_because_it_was_fetched(self) -> None:
        external_research = {
            "state": "content_unavailable",
            "multi_source_research": {
                "provider_reports": [_news_report("Local weather forecast improves this weekend | publisher=Wire | published=unknown")],
                "research_plan": {"queries": {"news": ["Samsung Electronics semiconductor cycle"]}},
                "evidence_bundle": {"evidence_strength": "exploratory", "conflict_status": "insufficient"},
            },
        }
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=45, symbols=5),
            external_research=external_research,
        )
        news = payload["autonomous_learning_v2"]["news_intelligence"]
        self.assertEqual(len(news["items"]), 1)
        self.assertEqual(news["items"][0]["news_research_action"], "ignore")
        self.assertEqual(news["actions_summary"], {"ignore": 1})

    def test_fixture_backed_news_is_never_registered_as_production_evidence(self) -> None:
        external_research = {
            "state": "content_unavailable",
            "multi_source_research": {
                "provider_reports": [
                    _news_report(
                        "Samsung faces trading halt amid liquidity crunch | publisher=Wire | published=unknown",
                        fixture_backed=True,
                    )
                ],
                "research_plan": {"queries": {"news": ["Samsung"]}},
                "evidence_bundle": {"evidence_strength": "exploratory", "conflict_status": "insufficient"},
            },
        }
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=45, symbols=5),
            external_research=external_research,
        )
        news = payload["autonomous_learning_v2"]["news_intelligence"]
        self.assertEqual(news["items"], [])
        self.assertEqual(news["fixture_items_excluded"], 1)

    def test_unresolved_conflict_from_evidence_bundle_starts_counter_hypothesis(self) -> None:
        external_research = {
            "state": "content_unavailable",
            "multi_source_research": {
                "provider_reports": [
                    _news_report("Samsung demand outlook unchanged | publisher=Wire | published=unknown")
                ],
                "research_plan": {"queries": {"news": ["Samsung"]}},
                "evidence_bundle": {"evidence_strength": "moderate", "conflict_status": "mixed"},
            },
        }
        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략을 처음부터 다시 연구해줘",
            symbol="005930",
            mode="research",
            baseline=_baseline(trades=45, symbols=5),
            external_research=external_research,
        )
        news = payload["autonomous_learning_v2"]["news_intelligence"]
        self.assertEqual(news["conflict_status"], "unresolved_conflict")
        self.assertEqual(news["items"][0]["news_research_action"], "start_counter_hypothesis")


if __name__ == "__main__":
    unittest.main()
