import sqlite3
import unittest

from gaon.runtime.agent_planner import AgentPlanExecutor, AgentPlanner, AgentPlanPolicy, AgentPlanStatus, SQLiteAgentPlanRepository
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


NOW = "2026-07-19T00:00:00Z"


class AgentPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.executor = SafeToolExecutor(default_tool_registry(self.connection), SQLiteToolAuditRepository(self.connection))

    def tearDown(self) -> None:
        self.connection.close()

    def test_schema_migrates_to_v27(self) -> None:
        self.assertGreaterEqual(SCHEMA_VERSION, 27)
        self.assertIsNotNone(self.connection.execute("SELECT name FROM sqlite_master WHERE name='agent_plans'").fetchone())

    def test_safe_multi_step_request_reads_tools_and_synthesizes(self) -> None:
        plan = AgentPlanner().plan("현재 챔피언과 최근 v5 결과를 비교해서 알려줘", created_at=NOW)
        result = AgentPlanExecutor(self.executor).execute(plan, actor_ref="test", now=NOW)

        self.assertEqual(result.status, AgentPlanStatus.COMPLETED)
        self.assertEqual([item["tool_name"] for item in result.outputs], ["champion_status", "v5_pipeline_history"])

    def test_approval_boundary_stops_without_execution(self) -> None:
        plan = AgentPlanner().plan("이 전략으로 배포 승인해줘", created_at=NOW)
        result = AgentPlanExecutor(self.executor).execute(plan, actor_ref="test", now=NOW)

        self.assertEqual(result.status, AgentPlanStatus.REQUIRES_HUMAN_APPROVAL)
        self.assertEqual(result.outputs, ())

    def test_policy_denies_overflow(self) -> None:
        plan = AgentPlanner().plan("현재 챔피언과 최근 v5 결과를 비교해서 알려줘", created_at=NOW)
        result = AgentPlanExecutor(self.executor, AgentPlanPolicy(max_steps=1)).execute(plan, actor_ref="test", now=NOW)

        self.assertEqual(result.status, AgentPlanStatus.DENIED)

    def test_repository_round_trip(self) -> None:
        plan = AgentPlanner().plan("가온 상태 알려줘", created_at=NOW)
        repository = SQLiteAgentPlanRepository(self.connection)
        repository.put(plan, updated_at=NOW)

        self.assertEqual(repository.list()[0].request_text, plan.request_text)


if __name__ == "__main__":
    unittest.main()
