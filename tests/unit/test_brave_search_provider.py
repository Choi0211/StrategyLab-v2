"""Brave Search provider: real-provider wiring, failure handling, and the
fixture fallback disclosure. No real network calls - the HTTP opener is
always a mock/fake in these tests."""
import io
import json
import unittest
from urllib.error import HTTPError

from gaon.runtime.external_research import (
    BraveSearchExternalResearchProvider,
    ExternalResearchError,
    ExternalResearchTool,
    create_external_research_provider,
    create_external_research_tool,
    normalize_external_results,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self, _limit: int) -> bytes:
        return self._body


def _opener_returning(payload: dict):
    def _opener(request, timeout):  # noqa: ARG001 - signature matches urlopen
        return _FakeResponse(payload)

    return _opener


def _opener_raising(exc: Exception):
    def _opener(request, timeout):  # noqa: ARG001
        raise exc

    return _opener


class BraveSearchProviderTests(unittest.TestCase):
    def test_missing_api_key_fails_closed(self):
        provider = BraveSearchExternalResearchProvider(api_key=None)
        with self.assertRaises(ExternalResearchError):
            ExternalResearchTool(provider).search("breakout volume", retrieved_at="2026-10-25T00:00:00Z")

    def test_successful_search_is_normalized_and_disclosed_as_real(self):
        payload = {
            "web": {
                "results": [
                    {
                        "title": "Korea breakout volume research",
                        "url": "https://example.com/research/breakout-volume",
                        "description": "Volume confirmation reduces false breakouts.",
                        "page_age": "2026-10-20T00:00:00",
                    },
                    {"title": "", "url": "https://example.com/empty-title"},
                ]
            }
        }
        provider = BraveSearchExternalResearchProvider(api_key="test-key", opener=_opener_returning(payload))
        result = ExternalResearchTool(provider).search("breakout volume", retrieved_at="2026-10-25T00:00:00Z")
        self.assertEqual(result["provider"], "brave_search")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["url"], "https://example.com/research/breakout-volume")
        warnings = " ".join(result["warnings"]).lower()
        self.assertNotIn("synthetic", warnings)
        self.assertNotIn("do not use", warnings)

    def test_one_bad_url_does_not_kill_the_whole_batch(self):
        payload = {
            "web": {
                "results": [
                    {"title": "Blocked SSRF target", "url": "http://127.0.0.1/admin"},
                    {"title": "Good result", "url": "https://example.com/good", "description": "ok"},
                ]
            }
        }
        provider = BraveSearchExternalResearchProvider(api_key="test-key", opener=_opener_returning(payload))
        result = ExternalResearchTool(provider).search("volume", retrieved_at="2026-10-25T00:00:00Z")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["url"], "https://example.com/good")

    def test_rate_limit_raises_external_research_error(self):
        exc = HTTPError("https://api.search.brave.com", 429, "Too Many Requests", {}, io.BytesIO(b""))
        provider = BraveSearchExternalResearchProvider(api_key="test-key", opener=_opener_raising(exc))
        with self.assertRaises(ExternalResearchError):
            ExternalResearchTool(provider).search("volume", retrieved_at="2026-10-25T00:00:00Z")

    def test_invalid_api_key_raises_external_research_error(self):
        exc = HTTPError("https://api.search.brave.com", 401, "Unauthorized", {}, io.BytesIO(b""))
        provider = BraveSearchExternalResearchProvider(api_key="bad-key", opener=_opener_raising(exc))
        with self.assertRaises(ExternalResearchError):
            ExternalResearchTool(provider).search("volume", retrieved_at="2026-10-25T00:00:00Z")

    def test_timeout_raises_external_research_error(self):
        provider = BraveSearchExternalResearchProvider(api_key="test-key", opener=_opener_raising(TimeoutError()))
        with self.assertRaises(ExternalResearchError):
            ExternalResearchTool(provider).search("volume", retrieved_at="2026-10-25T00:00:00Z")


class ExternalResearchFactoryTests(unittest.TestCase):
    def test_factory_selects_fixture_without_api_key(self):
        provider = create_external_research_provider(provider_name="brave_search", api_key=None)
        self.assertEqual(provider.name, "fixture")

    def test_factory_selects_brave_with_api_key(self):
        provider = create_external_research_provider(provider_name="brave_search", api_key="k")
        self.assertEqual(provider.name, "brave_search")

    def test_tool_discloses_fallback_from_requested_real_provider(self):
        tool = create_external_research_tool(provider_name="brave_search", api_key=None)
        result = tool.search("breakout", retrieved_at="2026-10-25T00:00:00Z")
        self.assertEqual(result["provider"], "fixture")
        self.assertEqual(result["requested_provider"], "brave_search")
        warnings = " ".join(result["warnings"]).lower()
        self.assertIn("not available", warnings)
        self.assertIn("not real external research", warnings)

    def test_tool_has_no_fallback_warning_when_fixture_was_the_default(self):
        tool = create_external_research_tool()
        result = tool.search("breakout", retrieved_at="2026-10-25T00:00:00Z")
        warnings = " ".join(result["warnings"]).lower()
        self.assertNotIn("not available", warnings)


class NormalizeExternalResultsRobustnessTests(unittest.TestCase):
    def test_skips_blocked_url_instead_of_raising(self):
        rows = (
            ("ok", "https://example.com/a", "snippet", None),
            ("blocked", "http://127.0.0.1/x", "snippet", None),
            ("also ok", "https://example.com/b", "snippet", None),
        )
        results = normalize_external_results(rows, max_results=5, retrieved_at="2026-10-25T00:00:00Z")
        self.assertEqual([r.url for r in results], ["https://example.com/a", "https://example.com/b"])


if __name__ == "__main__":
    unittest.main()
