"""GaonRuntimeConfig gating for the real (paid) external research provider."""
import unittest

from gaon.runtime.config import GaonRuntimeConfig, load_runtime_config
from gaon.runtime.errors import ConfigurationError


class ExternalResearchConfigTests(unittest.TestCase):
    def test_default_is_fixture(self):
        config = GaonRuntimeConfig()
        self.assertEqual(config.external_research_provider, "fixture")
        self.assertEqual(config.effective_external_research_provider, "fixture")

    def test_brave_search_without_paid_provider_enabled_reads_back_as_fixture(self):
        config = GaonRuntimeConfig(external_research_provider="brave_search", external_research_api_key="k")
        self.assertEqual(config.external_research_provider, "brave_search")
        self.assertEqual(config.effective_external_research_provider, "fixture")

    def test_brave_search_with_paid_provider_enabled_is_effective(self):
        config = GaonRuntimeConfig(
            external_research_provider="brave_search",
            external_research_api_key="k",
            free_only_mode=False,
            paid_provider_enabled=True,
        )
        self.assertEqual(config.effective_external_research_provider, "brave_search")

    def test_unknown_provider_name_is_rejected_at_construction(self):
        with self.assertRaises(ConfigurationError):
            GaonRuntimeConfig(external_research_provider="bing")

    def test_load_runtime_config_reads_brave_env_vars(self):
        env = {
            "GAON_EXTERNAL_RESEARCH_PROVIDER": "brave_search",
            "GAON_BRAVE_SEARCH_API_KEY": "secret-key",
            "GAON_EXTERNAL_RESEARCH_TIMEOUT_SECONDS": "7",
        }
        config = load_runtime_config(env)
        self.assertEqual(config.external_research_provider, "brave_search")
        self.assertEqual(config.external_research_api_key, "secret-key")
        self.assertEqual(config.external_research_timeout_seconds, 7.0)
        self.assertNotIn("secret-key", repr(config))
        # Loading config never crashes on a half-configured paid provider;
        # it just reads back as fixture until paid_provider_enabled is set.
        self.assertEqual(config.effective_external_research_provider, "fixture")


if __name__ == "__main__":
    unittest.main()
