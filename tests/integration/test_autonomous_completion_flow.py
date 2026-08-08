import unittest

from gaon.runtime.cli import main as cli_main


class AutonomousCompletionFlowTests(unittest.TestCase):
    def test_sprint156_adaptive_validation_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-adaptive-validation-release-check", "--db", ":memory:"]), 0)


if __name__ == "__main__":
    unittest.main()
