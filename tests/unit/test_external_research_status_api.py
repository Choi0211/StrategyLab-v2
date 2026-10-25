"""GET /gaon/research/external_provider_status: read-only status the
dashboard uses to show plainly whether real external search is connected,
or everything is still fixture-only. Never runs a search itself."""
import unittest
from unittest.mock import patch

from gaon.runtime.web_api import _handle_external_research_status


class ExternalResearchStatusApiTests(unittest.TestCase):
    def test_default_env_reports_fixture_not_connected(self):
        with patch.dict("os.environ", {}, clear=True):
            status, payload = _handle_external_research_status()
        self.assertEqual(status, 200)
        self.assertEqual(payload["configured_provider"], "fixture")
        self.assertEqual(payload["effective_provider"], "fixture")
        self.assertFalse(payload["real_search_connected"])
        self.assertEqual(payload["reason"], "fixture_configured")

    def test_brave_requested_without_key_reports_no_api_key(self):
        env = {"GAON_EXTERNAL_RESEARCH_PROVIDER": "brave_search"}
        with patch.dict("os.environ", env, clear=True):
            status, payload = _handle_external_research_status()
        self.assertEqual(status, 200)
        self.assertFalse(payload["real_search_connected"])
        self.assertEqual(payload["reason"], "no_api_key")

    def test_brave_requested_with_key_but_paid_disabled_reports_that(self):
        env = {
            "GAON_EXTERNAL_RESEARCH_PROVIDER": "brave_search",
            "GAON_BRAVE_SEARCH_API_KEY": "k",
        }
        with patch.dict("os.environ", env, clear=True):
            status, payload = _handle_external_research_status()
        self.assertFalse(payload["real_search_connected"])
        self.assertEqual(payload["reason"], "paid_provider_not_enabled")

    def test_fully_configured_brave_reports_connected(self):
        env = {
            "GAON_EXTERNAL_RESEARCH_PROVIDER": "brave_search",
            "GAON_BRAVE_SEARCH_API_KEY": "k",
            "GAON_FREE_ONLY_MODE": "false",
            "GAON_PAID_PROVIDER_ENABLED": "true",
        }
        with patch.dict("os.environ", env, clear=True):
            status, payload = _handle_external_research_status()
        self.assertEqual(payload["effective_provider"], "brave_search")
        self.assertTrue(payload["real_search_connected"])
        self.assertEqual(payload["reason"], "connected")
        self.assertNotIn("k", str(payload))


if __name__ == "__main__":
    unittest.main()
