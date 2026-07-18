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


def _request(tool_name: str, arguments: dict[str, object] | None = None) -> ToolRequest:
    return ToolRequest(
        tool_name=tool_name,
        arguments=arguments or {},
        requested_by="test",
        requested_at="2026-07-19T00:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
