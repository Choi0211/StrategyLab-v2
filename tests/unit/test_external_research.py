import unittest

from gaon.runtime.external_research import ExternalResearchError, ExternalResearchTool, FreshnessStatus, structured_data, validate_external_url, validate_redirect_chain
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest, default_tool_registry
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-20T00:00:00Z"


class ExternalResearchTests(unittest.TestCase):
    def test_web_search_returns_citations_and_freshness(self) -> None:
        result = ExternalResearchTool().search("market volatility", max_results=2, retrieved_at=NOW)
        self.assertEqual(result["provider"], "fixture")
        self.assertEqual(len(result["results"]), 2)
        first = result["results"][0]
        self.assertIn("metadata", first)
        self.assertIn("citation_id", first["metadata"])
        self.assertIn(first["metadata"]["freshness"], {FreshnessStatus.FRESH.value, FreshnessStatus.STALE.value, FreshnessStatus.UNKNOWN.value})

    def test_ssrf_blocks_loopback_private_metadata_and_bad_scheme(self) -> None:
        for url in ("http://127.0.0.1/status", "http://10.0.0.1/status", "http://metadata.google.internal/latest", "file:///tmp/secret"):
            with self.subTest(url=url):
                with self.assertRaises(ExternalResearchError):
                    validate_external_url(url)

    def test_redirect_chain_validates_every_hop(self) -> None:
        with self.assertRaises(ExternalResearchError):
            validate_redirect_chain(("https://example.com/start", "http://169.254.169.254/latest"))

    def test_structured_tools_do_not_fabricate_unconfigured_data(self) -> None:
        fx = structured_data("exchange_rate", {"base": "USD", "quote": "KRW"}, retrieved_at=NOW)
        self.assertEqual(fx["freshness"], "unknown")
        self.assertEqual(fx["data"]["status"], "provider_not_configured")

    def test_external_tools_are_read_only_and_audited(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            executor = SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit)
            result = executor.execute(ToolRequest("news_search", {"query": "market", "max_results": 1}, "test", NOW))
            self.assertEqual(result.status, "success")
            audits = store.tool_audit.list(tool_name="news_search")
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].risk_level, "read_only")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
