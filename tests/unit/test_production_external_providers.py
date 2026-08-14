from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from gaon.knowledge.multi_source_research import (
    MultiSourceResearchPlan,
    MultiSourceResearchPolicy,
    ProviderState,
    SourceCategory,
)
from gaon.knowledge.production_external_providers import (
    FetchResult,
    ProductionCorporateAdapter,
    ProductionDartRegulatoryAdapter,
    ProductionNewsRssAdapter,
    production_external_provider_adapters,
)


def _plan() -> MultiSourceResearchPlan:
    return MultiSourceResearchPlan(
        plan_id="plan:test",
        research_topic="breakout strategy robustness",
        symbol="005930",
        strategy_family="breakout",
        providers=tuple(SourceCategory),
        queries={item.value: ("Samsung Electronics breakout robustness",) for item in SourceCategory},
        policy=MultiSourceResearchPolicy(),
    )


class ProductionExternalProviderTests(unittest.TestCase):
    def test_factory_fills_expected_categories(self) -> None:
        adapters = production_external_provider_adapters(symbol="005930")
        self.assertEqual(
            [item.category for item in adapters],
            [
                SourceCategory.CORPORATE,
                SourceCategory.REGULATORY,
                SourceCategory.NEWS,
                SourceCategory.PROFESSIONAL_RESEARCH,
                SourceCategory.WEB,
            ],
        )

    def test_corporate_adapter_uses_real_content_contract(self) -> None:
        def fetcher(url: str, hosts: tuple[str, ...]) -> FetchResult:
            self.assertIn("www.samsung.com", hosts)
            return FetchResult(
                final_url=url,
                content_type="text/html",
                body=b"<html><body>Samsung earnings improved while market risk remains.</body></html>",
            )

        report = ProductionCorporateAdapter(symbol="005930", fetcher=fetcher).research(_plan())
        self.assertEqual(report.state, ProviderState.SUCCESS)
        self.assertEqual(len(report.claims), 1)
        self.assertTrue(report.claims[0].validation_evidence)
        self.assertFalse(report.fixture_backed)

    def test_dart_is_honestly_not_configured_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            report = ProductionDartRegulatoryAdapter(symbol="005930").research(_plan())
        self.assertEqual(report.state, ProviderState.NOT_CONFIGURED)
        self.assertIn("GAON_DART_API_KEY_missing", report.blockers)

    def test_dart_fetches_list_and_document_without_persisting_key(self) -> None:
        import io
        import zipfile

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("report.xml", "<DOCUMENT><P>Market risk and semiconductor demand uncertainty.</P></DOCUMENT>")
        zipped = archive.getvalue()

        def fetcher(url: str, hosts: tuple[str, ...]) -> FetchResult:
            self.assertEqual(hosts, ("opendart.fss.or.kr",))
            if "list.json" in url:
                payload = {
                    "status": "000",
                    "list": [
                        {"rcept_no": "20260814000001", "report_nm": "Business Report", "rcept_dt": "20260814"}
                    ],
                }
                return FetchResult(url, "application/json", json.dumps(payload).encode("utf-8"))
            self.assertIn("document.xml", url)
            return FetchResult(url, "application/zip", zipped)

        with patch.dict(os.environ, {"GAON_DART_API_KEY": "x" * 40}, clear=True):
            report = ProductionDartRegulatoryAdapter(symbol="005930", fetcher=fetcher).research(_plan())
        self.assertEqual(report.state, ProviderState.SUCCESS)
        self.assertEqual(len(report.claims), 1)
        self.assertNotIn("x" * 40, report.claims[0].locator)
        self.assertTrue(report.claims[0].validation_evidence)

    def test_news_rss_is_idea_only(self) -> None:
        rss = b"""<?xml version='1.0' encoding='UTF-8'?>
        <rss><channel>
          <item><title>Samsung chip demand improves</title><source>Example News</source><pubDate>Fri, 14 Aug 2026 10:00:00 GMT</pubDate></item>
          <item><title>Memory pricing risk remains</title><source>Another News</source><pubDate>Fri, 14 Aug 2026 11:00:00 GMT</pubDate></item>
        </channel></rss>"""

        def fetcher(url: str, hosts: tuple[str, ...]) -> FetchResult:
            self.assertEqual(hosts, ("news.google.com",))
            return FetchResult(url, "application/rss+xml", rss)

        with patch.dict(os.environ, {}, clear=True):
            report = ProductionNewsRssAdapter(symbol="005930", fetcher=fetcher).research(_plan())
        self.assertEqual(report.state, ProviderState.SUCCESS)
        self.assertEqual(len(report.claims), 1)
        self.assertTrue(report.claims[0].idea_evidence)
        self.assertFalse(report.claims[0].validation_evidence)


if __name__ == "__main__":
    unittest.main()
