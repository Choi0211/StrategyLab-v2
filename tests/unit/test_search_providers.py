import unittest

from gaon.research.search import FakeSearchProvider, OptionalWebSearchProvider, RssAtomSearchProvider, SearchQuery, canonical_url, record_search_metrics, search_event
from gaon.runtime.metrics import MetricsCollector


class SearchProvidersTest(unittest.TestCase):
    def test_normalization_result_limit_content_limit_and_duplicates(self) -> None:
        provider = FakeSearchProvider(
            (
                ("A", "HTTPS://Example.COM/a/", "x" * 100),
                ("A duplicate", "https://example.com/a", "duplicate"),
                ("B", "https://example.com/b", "content-b"),
            )
        )
        results = provider.search(SearchQuery("q", "fake", max_results=2, allowed_domains=("example.com",), max_content_chars=10))

        self.assertEqual(canonical_url("HTTPS://Example.COM/a/"), "https://example.com/a")
        self.assertEqual(len(results), 2)
        self.assertEqual(len(results[0].content), 10)

    def test_provider_disabled_timeout_and_bounded_retry(self) -> None:
        disabled = FakeSearchProvider((), enabled=False)
        with self.assertRaises(PermissionError):
            disabled.search(SearchQuery("q", "fake"))

        calls = {"count": 0}

        def failing(_: SearchQuery):
            calls["count"] += 1
            raise RuntimeError("synthetic")

        provider = OptionalWebSearchProvider(failing, enabled=True, retries=2)
        with self.assertRaises(RuntimeError):
            provider.search(SearchQuery("q", "free-web", timeout_seconds=1))
        self.assertEqual(calls["count"], 2)

        def timeout(_: SearchQuery):
            raise TimeoutError("synthetic")

        with self.assertRaises(TimeoutError):
            OptionalWebSearchProvider(timeout, enabled=True).search(SearchQuery("q", "free-web"))

    def test_rss_fixture_no_live_network(self) -> None:
        rss = "<rss><channel><item><title>ORB evidence</title><link>https://example.com/orb</link></item></channel></rss>"
        results = RssAtomSearchProvider(rss).search(SearchQuery("ORB", "rss"))

        self.assertEqual(results[0].title, "ORB evidence")
        self.assertEqual(results[0].source.provider, "rss")

    def test_metrics_and_event(self) -> None:
        metrics = MetricsCollector()
        record_search_metrics(metrics, provider="fake", count=2)
        event = search_event("fake", 2, occurred_at="2026-07-18T00:00:00Z")

        self.assertIn("gaon_search_requests_total", metrics.snapshot().to_text())
        self.assertEqual(event.event_type, "SearchCompleted")


if __name__ == "__main__":
    unittest.main()
