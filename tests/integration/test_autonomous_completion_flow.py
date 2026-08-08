import unittest

from gaon.runtime.cli import main as cli_main


class AutonomousCompletionFlowTests(unittest.TestCase):
    def test_sprint156_adaptive_validation_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-adaptive-validation-release-check", "--db", ":memory:"]), 0)

    def test_sprint157_autonomous_research_planner_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-autonomous-research-planner-release-check", "--db", ":memory:"]), 0)

    def test_sprint158_strategy_candidate_generation_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-strategy-candidate-generation-release-check", "--db", ":memory:"]), 0)

    def test_sprint159_research_critic_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-research-critic-release-check", "--db", ":memory:"]), 0)

    def test_sprint160_learning_memory_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-autonomous-learning-memory-release-check", "--db", ":memory:"]), 0)

    def test_sprint161_autonomous_research_cycle_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-autonomous-research-cycle-release-check", "--db", ":memory:"]), 0)


if __name__ == "__main__":
    unittest.main()
