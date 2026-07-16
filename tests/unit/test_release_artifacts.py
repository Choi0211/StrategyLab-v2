from pathlib import Path
import unittest


class ReleaseArtifactsTest(unittest.TestCase):
    def test_release_documents_exist(self) -> None:
        root = Path(__file__).resolve().parents[2]
        required = [
            "docs/architecture/GaonDevelopmentContract.md",
            "docs/architecture/Sprint11_Brief.md",
            "docs/adr/ADR-0001-learning-memory-core.md",
            "docs/adr/ADR-0003-research-brain-contracts.md",
            "docs/rfc/RFC-0001-sprint11-learning-engine.md",
            "docs/rfc/RFC-0002-sprint11-research-brain.md",
            "docs/research/ResearchBrain.md",
            "docs/learning/LearningMemory.md",
            "docs/conversation/ConversationEngine.md",
            "docs/releases/CHANGELOG.md",
            "docs/releases/ReleaseNotes.md",
            "docs/operations/Runbook.md",
            "scripts/verify_release.py",
        ]
        for path in required:
            self.assertTrue((root / path).exists(), path)


if __name__ == "__main__":
    unittest.main()
