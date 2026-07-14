from pathlib import Path
import unittest

from strategylab.core import load_config


class ConfigLoaderTest(unittest.TestCase):
    def test_loads_example_config_without_secrets(self) -> None:
        config = load_config(Path("config/config.example.yaml"))

        self.assertEqual(config.app_name, "StrategyLab v2")
        self.assertEqual(config.environment, "development")
        self.assertEqual(config.log_level, "INFO")
        self.assertIn("core", config.enabled_modules)
        self.assertIn("notification", config.enabled_modules)
        self.assertEqual(config.plugin_paths, ())


if __name__ == "__main__":
    unittest.main()
