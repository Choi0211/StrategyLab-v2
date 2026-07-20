import unittest

from gaon.research.strategy_research import ResearchRecommendation, SQLiteStrategyResearchRepository, StrategyResearchOrchestrator, StrategyResearchPlanner
from gaon.runtime.agent_planner import AgentPlanPolicy, AgentPlanner
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-20T00:00:00Z"


class StrategyResearchTests(unittest.TestCase):
    def test_research_planner_creates_bounded_steps(self) -> None:
        plan = StrategyResearchPlanner().create_plan("Research a challenger", created_at=NOW)
        self.assertEqual(plan.status.value, "created")
        self.assertIn("compare_with_champion", plan.steps)
        self.assertLessEqual(len(plan.steps), 8)

    def test_agent_planner_selects_external_read_only_tools(self) -> None:
        plan = AgentPlanner().plan("research market news and exchange rate", created_at=NOW)
        tool_names = [step.tool_name for step in plan.steps if step.tool_name]
        self.assertIn("market_data", tool_names)
        self.assertIn("exchange_rate", tool_names)
        self.assertIn("news_search", tool_names)
        self.assertEqual(AgentPlanPolicy(max_steps=10).validate(plan).value, "created")

    def test_strategy_research_pipeline_records_report_without_promotion(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            report = StrategyResearchOrchestrator(store._connection).run("Research safer breakout challenger", run_id="unit-research", actor_ref="test", requested_at=NOW)
            self.assertEqual(report.recommendation, ResearchRecommendation.RECOMMEND)
            self.assertIsNotNone(report.backtest_result_id)
            self.assertFalse(report.champion_comparison["automatic_promotion"])
            stored = SQLiteStrategyResearchRepository(store._connection).list_reports()
            self.assertEqual(len(stored), 1)
        finally:
            store.close()

    def test_intraday_missing_data_returns_data_unavailable(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            report = StrategyResearchOrchestrator(store._connection).run("Research 1m intraday breakout", run_id="intraday", actor_ref="test", requested_at=NOW, timeframe="1m")
            self.assertEqual(report.recommendation, ResearchRecommendation.DATA_UNAVAILABLE)
            self.assertIsNone(report.backtest_result_id)
            self.assertIn("intraday data unavailable", report.limitations)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
