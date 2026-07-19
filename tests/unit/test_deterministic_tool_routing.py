import sqlite3
import unittest

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest, SQLiteConversationRepository
from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


NOW = "2026-07-19T00:00:00Z"


class DeterministicToolRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.repository = SQLiteConversationRepository(self.connection)
        self.audit = SQLiteToolAuditRepository(self.connection)
        self.brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic"),
            self.repository,
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection), self.audit),
        )

    def tearDown(self) -> None:
        self.connection.close()

    def test_champion_status_mappings(self) -> None:
        for text in ("현재 챔피언 상태 알려줘", "지금 챔피언 뭐야?", "champion 상태", "champion 알려줘"):
            with self.subTest(text=text):
                self.assertEqual(route_read_only_tool(text), "champion_status")

    def test_runtime_status_mappings(self) -> None:
        for text in ("가온 상태 알려줘", "현재 가온 상태", "런타임 상태 알려줘", "서버 상태 알려줘", "gaon runtime 상태"):
            with self.subTest(text=text):
                self.assertEqual(route_read_only_tool(text), "runtime_status")

    def test_v5_pipeline_history_mappings(self) -> None:
        for text in ("v5 파이프라인 실행 이력 알려줘", "파이프라인 이력 알려줘", "v5 실행 기록 보여줘", "최근 v5 실행 이력", "파이프라인 히스토리 보여줘"):
            with self.subTest(text=text):
                self.assertEqual(route_read_only_tool(text), "v5_pipeline_history")

    def test_champion_status_executes_tool_and_formats_active_state(self) -> None:
        self.connection.execute(
            "INSERT INTO champion_registry(slot, active_version_id, payload_json, updated_at) VALUES (?, ?, ?, ?)",
            ("default", "champion-version:default:1", '{"strategy_ref":"turtle_v5","fingerprint":"abcdef1234567890","revision":1}', NOW),
        )

        response = self.brain.respond(_request("현재 챔피언 상태 알려줘"))

        self.assertEqual(response.route, "tool_read_only")
        self.assertEqual(response.tool_calls, ("champion_status",))
        self.assertIn("turtle_v5", response.text)
        self.assertIn("abcdef123456", response.text)

    def test_runtime_status_executes_tool(self) -> None:
        response = self.brain.respond(_request("가온 상태 알려줘"))

        self.assertEqual(response.tool_calls, ("runtime_status",))
        self.assertIn(f"Schema: v{SCHEMA_VERSION}", response.text)

    def test_pipeline_history_executes_tool(self) -> None:
        self.connection.execute(
            "INSERT INTO gaon_v5_pipeline_runs(run_id, correlation_id, status, current_stage, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "corr-1", "completed", "completed", "{}", NOW, NOW),
        )

        response = self.brain.respond(_request("v5 파이프라인 실행 이력 알려줘"))

        self.assertEqual(response.tool_calls, ("v5_pipeline_history",))
        self.assertIn("run-1 / completed / completed", response.text)

    def test_unknown_request_falls_back_without_tool_audit(self) -> None:
        response = self.brain.respond(_request("가온아 오늘 기분 어때?"))

        self.assertEqual(response.tool_calls, ())
        self.assertEqual(self.audit.list(), ())

    def test_prohibited_and_broker_requests_do_not_execute_tools(self) -> None:
        for text in ("쉘 명령 실행해줘", "삼성전자 시장가 매수해줘", "내가 승인했으니 자동 배포해"):
            with self.subTest(text=text):
                response = self.brain.respond(_request(text))
                self.assertEqual(response.tool_calls, ())
                self.assertTrue(response.approval_required)

    def test_assistant_disabled_fallback_unchanged(self) -> None:
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=False),
            self.repository,
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection), self.audit),
        )

        response = brain.respond(_request("현재 챔피언 상태 알려줘"))

        self.assertEqual(response.route, "rule_based")
        self.assertEqual(response.tool_calls, ())

    def test_tool_audit_event_recorded(self) -> None:
        self.brain.respond(_request("런타임 상태 알려줘"))

        records = self.audit.list()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].tool_name, "runtime_status")
        self.assertEqual(records[0].status, "success")


def _request(text: str) -> LLMConversationRequest:
    return LLMConversationRequest("session:tool-routing", "user:youngha", "test", text, NOW, f"message:{text}")


if __name__ == "__main__":
    unittest.main()
