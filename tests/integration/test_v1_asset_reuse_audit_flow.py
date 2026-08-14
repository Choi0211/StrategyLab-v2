from contextlib import redirect_stdout
from io import StringIO
import unittest

from gaon.runtime.cli import main


class V1AssetReuseAuditFlowTests(unittest.TestCase):
    def test_v1_v2_audit_release_check_cli_commands_pass(self) -> None:
        commands = (
            "gaon-production-v1-asset-reuse-audit-release-check",
            "gaon-production-v1-v2-authoritative-path-release-check",
            "gaon-production-no-unintended-duplicate-engine-release-check",
            "gaon-production-research-memory-continuity-release-check",
            "gaon-production-legacy-path-isolation-release-check",
            "gaon-production-v1-v2-final-integration-release-check",
        )

        for command in commands:
            with self.subTest(command=command):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(0, main([command]))
                text = output.getvalue()
                self.assertIn(f"{command}: PASS", text)
                self.assertIn("verdict=GAON_V1/V2_INTEGRATION_COMPLETE", text)
                self.assertIn("DUPLICATE_ENGINE_STATUS=no_unintended_duplicate_engine", text)
                self.assertIn("strategy_mutated=false", text)
                self.assertIn("order_executed=false", text)
                self.assertIn("safety=pass", text)


if __name__ == "__main__":
    unittest.main()
