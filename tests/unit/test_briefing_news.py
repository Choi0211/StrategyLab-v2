import unittest

from gaon.knowledge.production_external_providers import FetchResult
from gaon.runtime.briefing_news import collect_pre_market_news
from gaon.runtime.daily_briefing import _compose_runtime_pre_market

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>코스피 외국인 순매수 확대</title><source>테스트뉴스</source><pubDate>Wed, 18 Nov 2026 00:10:00 GMT</pubDate></item>
<item><title>미국 증시 상승 마감</title><source>테스트뉴스</source><pubDate>Wed, 18 Nov 2026 00:05:00 GMT</pubDate></item>
</channel></rss>""".encode("utf-8")
NOW = "2026-11-17T23:55:00Z"


def fake_fetch(url, hosts):
    return FetchResult(final_url=url, content_type="application/rss+xml", body=RSS)


def failing_fetch(url, hosts):
    raise OSError("network down")


class BriefingNewsTest(unittest.TestCase):
    def test_collects_and_dedupes_headlines(self):
        items = collect_pre_market_news(NOW, fetcher=fake_fetch)
        headlines = [i.headline for i in items]
        self.assertIn("코스피 외국인 순매수 확대", headlines)
        self.assertEqual(len(headlines), len(set(headlines)))
        self.assertTrue(all(i.production_safe for i in items))

    def test_network_failure_returns_empty_without_raising(self):
        self.assertEqual(collect_pre_market_news(NOW, fetcher=failing_fetch), ())

    def test_briefing_lists_news_when_available(self):
        text = _compose_runtime_pre_market(
            NOW, news_items_provider=lambda: collect_pre_market_news(NOW, fetcher=fake_fetch)
        )
        self.assertIn("코스피 외국인 순매수 확대", text)
        self.assertNotIn("반영할 만한 새 뉴스 근거가 없습니다", text)

    def test_briefing_still_sends_when_news_provider_raises(self):
        def boom():
            raise RuntimeError("x")

        text = _compose_runtime_pre_market(NOW, news_items_provider=boom)
        self.assertIn("반영할 만한 새 뉴스 근거가 없습니다", text)


if __name__ == "__main__":
    unittest.main()
