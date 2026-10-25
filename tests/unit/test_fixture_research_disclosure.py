"""Fixture research must never be presented as real-world evidence."""
import unittest

from gaon.runtime.external_research import ExternalResearchTool, structured_data


class FixtureDisclosureTests(unittest.TestCase):
    def test_fixture_search_is_clearly_disclosed(self):
        result = ExternalResearchTool().search("breakout", retrieved_at="2026-10-25T00:00:00Z")
        self.assertEqual(result["provider"], "fixture")
        warnings = " ".join(result["warnings"]).lower()
        self.assertIn("synthetic", warnings)
        self.assertIn("not verified external research", warnings)
        self.assertIn("do not use", warnings)
        self.assertTrue(result["results"])

    def test_fixture_news_search_is_disclosed(self):
        result = structured_data("news_search", {"query": "volume"}, retrieved_at="2026-10-25T00:00:00Z")
        self.assertEqual(result["provider"], "fixture")
        self.assertTrue(any("synthetic" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
