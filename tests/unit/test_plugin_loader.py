from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from strategylab.core import PluginLoader


class PluginLoaderTest(unittest.TestCase):
    def test_plugin_loader_ignores_missing_paths(self) -> None:
        loader = PluginLoader(paths=(Path("missing-plugins"),))

        self.assertEqual(loader.discover(), ())


    def test_plugin_loader_discovers_plugin_directories(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "sample"
            plugin.mkdir()
            (plugin / "plugin.toml").write_text('name = "sample"\n', encoding="utf-8")

            loader = PluginLoader(paths=(root,))

            discovered = loader.discover()
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0].name, "sample")
            self.assertEqual(discovered[0].path, plugin)


if __name__ == "__main__":
    unittest.main()
