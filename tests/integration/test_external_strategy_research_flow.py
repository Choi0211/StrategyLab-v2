import unittest
from unittest.mock import patch

from gaon.research.strategy_research import StrategyResearchOrchestrator
from gaon.runtime.agent_planner import AgentPlanExecutor, AgentPlanPolicy, AgentPlanner
from gaon.runtime.llm_tools import SafeToolExecutor, default_tool_registry
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-20T00:00:00Z"


class ExternalStrategyResearchFlowTests(unittest.TestCase):
    @patch("gaon.runtime.research_media_tools._search_duckduckgo", return_value=[
        {"title": "Test evidence", "url": "https://example.com/research", "snippet": "Deterministic market news and weather evidence"}
    ])
    def test_multi_tool_external_research_plan_executes_and_strategy_report_is_created(self, search) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            executor = SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit)
            plan = AgentPlanner().plan("research market news exchange rate for Korean breakout strategy", created_at=NOW)
            result = AgentPlanExecutor(executor, AgentPlanPolicy(max_steps=10)).execute(plan, actor_ref="integration", now=NOW)
            self.assertEqual(result.status.value, "completed")
            tool_names = {output["tool_name"] for output in result.outputs}
            self.assertTrue({"market_data", "exchange_rate", "news_search"}.issubset(tool_names))
            report = StrategyResearchOrchestrator(store._connection).run("Research Korean breakout challenger", run_id="integration-research", actor_ref="integration", requested_at=NOW)
            self.assertEqual(report.recommendation.value, "recommend")
            self.assertFalse(report.champion_comparison["automatic_promotion"])
            self.assertGreaterEqual(len(store.tool_audit.list()), 3)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
