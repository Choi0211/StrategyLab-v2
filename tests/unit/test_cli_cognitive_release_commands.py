"""CLI cognitive checks must not fail due to local serializer shadowing."""

import subprocess
import sys
import unittest


class CognitiveCliReleaseCommandsTests(unittest.TestCase):
    def test_both_release_check_commands(self):
        for command in ("gaon-cognitive-core-v1-release-check", "gaon-unified-conversation-release-check"):
            with self.subTest(command=command):
                completed = subprocess.run(
                    [sys.executable, "-m", "gaon.runtime.cli", command],
                    capture_output=True, text=True, timeout=90, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertIn(f"{command}: PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
