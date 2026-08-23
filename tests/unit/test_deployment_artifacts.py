"""Tests for the deploy/ artifacts portability release check.

Production has never emitted a promotion-ready candidate before this
task's own audit found the pipeline was actually fine (see
test_research_mission.py's PromotionReadinessReachabilityReleaseCheckTests)
- but this codebase has repeatedly found the OPPOSITE problem elsewhere:
a `production_*_release_check` function that existed but had no real
caller, so its assertions never actually ran under
`python -m unittest discover` / scripts/verify_release.py. This test file
IS the caller for
production_deployment_artifacts_no_pc_dependency_release_check, following
the same convention every other module in this codebase already uses.
"""
import unittest

from gaon.runtime.cli import production_deployment_artifacts_no_pc_dependency_release_check


class DeploymentArtifactsNoPcDependencyReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes_against_the_real_deploy_directory(self) -> None:
        payload = production_deployment_artifacts_no_pc_dependency_release_check()
        for key in (
            "scanned_at_least_one_file",
            "no_windows_path_literal",
            "no_dev_machine_username_literal",
            "no_secret_shaped_value",
        ):
            self.assertTrue(payload[key], key)
        self.assertGreater(payload["scanned_file_count"], 0)
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])
        self.assertEqual(payload["safety"], "pass")

    def test_release_check_is_deterministic_across_runs(self) -> None:
        first = production_deployment_artifacts_no_pc_dependency_release_check()
        second = production_deployment_artifacts_no_pc_dependency_release_check()
        self.assertEqual(dict(first), dict(second))

    def test_detects_a_real_windows_path_literal(self) -> None:
        """Proves the check isn't a tautology: it must actually fail when a
        Windows-style absolute path is present, not just pass by construction."""
        import re

        from gaon.runtime.cli import _DEPLOY_WINDOWS_PATH_PATTERN_SOURCE

        pattern = re.compile(_DEPLOY_WINDOWS_PATH_PATTERN_SOURCE)
        self.assertIsNotNone(pattern.search(r"D:\backups\gaon-runtime.sqlite"))
        # And must NOT false-positive on an ordinary URL scheme.
        self.assertIsNone(pattern.search("https://example.invalid/gaon/health"))

    def test_detects_secret_shaped_values(self) -> None:
        import re

        from gaon.runtime.cli import _DEPLOY_SECRET_SHAPED_PATTERN_SOURCES

        patterns = [re.compile(p) for p in _DEPLOY_SECRET_SHAPED_PATTERN_SOURCES]
        self.assertTrue(any(p.search("sk-ant-api03-abcdefghijklmnop") for p in patterns))
        self.assertTrue(any(p.search("AKIAABCDEFGHIJKLMNOP") for p in patterns))
        self.assertFalse(any(p.search("<set-private-token-outside-git>") for p in patterns))


class DeploymentArtifactsNoPcDependencyCliWiringTests(unittest.TestCase):
    """CLI wiring, following the exact existing gaon-production-*-release-check
    pattern used throughout this codebase (e.g. EconomicViabilityGateCliWiringTests
    in test_strategy_candidate.py)."""

    def test_release_check_cli_passes(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        from gaon.runtime.cli import main as cli_main

        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(["gaon-production-deployment-artifacts-no-pc-dependency-release-check"])
        self.assertEqual(exit_code, 0)
        printed = output.getvalue()
        self.assertIn("gaon-production-deployment-artifacts-no-pc-dependency-release-check: PASS", printed)
        self.assertIn("no_windows_path_literal=true", printed)
        self.assertIn("no_secret_shaped_value=true", printed)
        self.assertIn("strategy_mutated=false", printed)
        self.assertIn("order_executed=false", printed)
        self.assertIn("champion_promoted=false", printed)
        self.assertIn("approval_bypassed=false", printed)


if __name__ == "__main__":
    unittest.main()
