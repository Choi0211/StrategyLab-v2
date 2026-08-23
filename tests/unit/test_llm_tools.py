import sqlite3
import unittest

from gaon.runtime.llm_tools import (
    SafeToolExecutor,
    SQLiteToolAuditRepository,
    ToolDefinition,
    ToolRegistry,
    ToolRequest,
    ToolRiskLevel,
    default_tool_registry,
)
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


class LLMToolFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.audit = SQLiteToolAuditRepository(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_schema_migrates_to_v24(self) -> None:
        self.assertGreaterEqual(SCHEMA_VERSION, 24)
        row = self.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llm_tool_audit'").fetchone()
        self.assertIsNotNone(row)

    def test_runtime_status_tool_succeeds_and_audits(self) -> None:
        executor = SafeToolExecutor(default_tool_registry(self.connection), self.audit)
        result = executor.execute(_request("runtime_status"))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output["schema_version"], SCHEMA_VERSION)
        self.assertEqual(self.audit.list()[0].tool_name, "runtime_status")

    def test_unknown_tool_is_denied_and_audited(self) -> None:
        executor = SafeToolExecutor(default_tool_registry(self.connection), self.audit)
        result = executor.execute(_request("shell_exec", {"command": "whoami"}))

        self.assertEqual(result.status, "denied")
        self.assertEqual(self.audit.list()[0].risk_level, "prohibited")

    def test_unexpected_arguments_are_denied(self) -> None:
        executor = SafeToolExecutor(default_tool_registry(self.connection), self.audit)
        result = executor.execute(_request("runtime_status", {"sql": "select *"}))

        self.assertEqual(result.status, "denied")

    def test_non_read_only_tool_requires_boundary_and_is_denied(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition("write_memory", "safe write disabled in conversational release", ToolRiskLevel.SAFE_WRITE),
            lambda _args: {"written": True},
        )
        result = SafeToolExecutor(registry, self.audit).execute(_request("write_memory"))

        self.assertEqual(result.status, "denied")

    def test_champion_status_missing_is_read_only(self) -> None:
        result = SafeToolExecutor(default_tool_registry(self.connection), self.audit).execute(_request("champion_status", {"slot": "default"}))

        self.assertEqual(result.status, "success")
        self.assertFalse(result.output["active"])

    def test_pipeline_history_limit_is_bounded(self) -> None:
        result = SafeToolExecutor(default_tool_registry(self.connection), self.audit).execute(_request("v5_pipeline_history", {"limit": 999}))

        self.assertEqual(result.status, "denied")


class FixtureGatedToolExposureTests(unittest.TestCase):
    """Self-improving-research fixture tools (strategy_critique,
    strategy_quality_score, research_candidate_compare) must not be handed
    to the assistant provider for a general/status conversation - a real
    production incident showed the provider picking one of these for
    "안녕하세요 현재 연결 상태를 알려주세요" and answering with fixture-tagged
    research data instead of a normal status reply."""

    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.executor = SafeToolExecutor(default_tool_registry(self.connection))

    def _names(self, request_text: str) -> set[str]:
        return {definition.name for definition in self.executor.assistant_tool_definitions(request_text)}

    def test_general_status_question_excludes_fixture_tools(self) -> None:
        names = self._names("안녕하세요 현재 연결 상태를 알려주세요")

        self.assertNotIn("strategy_critique", names)
        self.assertNotIn("strategy_quality_score", names)
        self.assertNotIn("research_candidate_compare", names)
        self.assertIn("runtime_status", names)

    def test_empty_request_excludes_fixture_tools(self) -> None:
        names = self._names("")

        self.assertNotIn("strategy_critique", names)
        self.assertNotIn("strategy_quality_score", names)
        self.assertNotIn("research_candidate_compare", names)

    def test_explicit_strategy_critique_request_includes_that_tool_only(self) -> None:
        names = self._names("이 전략의 약점을 비판해줘")

        self.assertIn("strategy_critique", names)
        self.assertNotIn("strategy_quality_score", names)
        self.assertNotIn("research_candidate_compare", names)

    def test_explicit_strategy_quality_request_includes_that_tool_only(self) -> None:
        names = self._names("이 전략 품질점수 알려줘")

        self.assertIn("strategy_quality_score", names)
        self.assertNotIn("strategy_critique", names)
        self.assertNotIn("research_candidate_compare", names)

    def test_explicit_candidate_compare_request_includes_that_tool_only(self) -> None:
        names = self._names("연구 후보들 비교해서 순위 매겨줘")

        self.assertIn("research_candidate_compare", names)
        self.assertNotIn("strategy_critique", names)
        self.assertNotIn("strategy_quality_score", names)


def _request(tool_name: str, arguments: dict[str, object] | None = None) -> ToolRequest:
    return ToolRequest(
        tool_name=tool_name,
        arguments=arguments or {},
        requested_by="test",
        requested_at="2026-07-19T00:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
