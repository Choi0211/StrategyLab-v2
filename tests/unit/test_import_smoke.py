import unittest


class ImportSmokeTest(unittest.TestCase):
    def test_package_imports(self) -> None:
        import gaon
        import gaon.learning
        import gaon.research
        import gaon.runtime
        import gaon.runtime.agent_planner
        import gaon.runtime.cli
        import strategylab
        import strategylab.backtest
        import strategylab.broker
        import strategylab.dashboard
        import strategylab.market
        import strategylab.notification
        import strategylab.portfolio
        import strategylab.reports
        import strategylab.research
        import strategylab.risk
        import strategylab.strategies

        self.assertEqual(gaon.__version__, "0.1.0")
        self.assertEqual(strategylab.__version__, "0.1.0")

    def test_runtime_agent_plan_status_imports_once(self) -> None:
        from gaon.runtime.agent_planner import AgentPlanStatus

        expected = {"created", "running", "completed", "failed", "denied", "requires_human_approval"}
        self.assertEqual({status.value for status in AgentPlanStatus}, expected)
        self.assertEqual(len([status for status in AgentPlanStatus if status.value == "failed"]), 1)


if __name__ == "__main__":
    unittest.main()
