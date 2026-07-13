from pathlib import Path
import unittest


class ReleaseArtifactsTest(unittest.TestCase):
    def test_release_documents_exist(self) -> None:
        root = Path(__file__).resolve().parents[2]
        required = [
            "docs/releases/CHANGELOG.md",
            "docs/releases/ReleaseNotes.md",
            "docs/operations/Runbook.md",
            "scripts/verify_release.py",
        ]
        for path in required:
            self.assertTrue((root / path).exists(), path)


if __name__ == "__main__":
    unittest.main()

