"""strategy-research-demo must keep working with the configurable external
research tool wired in (defaults to fixture when no paid provider is set)."""
import tempfile
import unittest

from gaon.runtime.cli import main


class StrategyResearchDemoExternalToolWiringTests(unittest.TestCase):
    def test_strategy_research_demo_runs_with_default_fixture_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/gaon.sqlite"
            self.assertEqual(main(["strategy-research-demo", "--db", db, "--run-id", "wiring-test"]), 0)

    def test_external_research_release_check_still_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/gaon.sqlite"
            self.assertEqual(main(["external-research-release-check", "--db", db]), 0)


if __name__ == "__main__":
    unittest.main()
