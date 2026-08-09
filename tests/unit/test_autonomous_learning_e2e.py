from __future__ import annotations

import unittest

from gaon.knowledge.autonomous_learning_e2e import autonomous_learning_e2e_release_check


class AutonomousLearningE2EReleaseCheckTests(unittest.TestCase):
    def test_release_check_reaches_human_approval_required(self) -> None:
        payload = autonomous_learning_e2e_release_check()

        self.assertEqual("proposed", payload["hypothesis_status"])
        self.assertEqual("accepted_for_review", payload["validation_status"])
        self.assertEqual("ranked", payload["ranking_status"])
        self.assertEqual("requires_human_approval", payload["promotion_status"])
        self.assertEqual("awaiting_human_approval", payload["human_gate_status"])
        self.assertEqual("pass", payload["safety"])


if __name__ == "__main__":
    unittest.main()
