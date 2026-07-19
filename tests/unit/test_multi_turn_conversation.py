import sqlite3
import unittest

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest, SQLiteConversationRepository, SQLiteConversationToolResultRepository
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


NOW = "2026-07-19T00:00:00Z"


class MultiTurnConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.repository = SQLiteConversationRepository(self.connection)
        self.tool_results = SQLiteConversationToolResultRepository(self.connection)
        self.brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True),
            self.repository,
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection), SQLiteToolAuditRepository(self.connection)),
            tool_result_repository=self.tool_results,
        )

    def tearDown(self) -> None:
        self.connection.close()

    def test_schema_migrates_to_v26(self) -> None:
        self.assertGreaterEqual(SCHEMA_VERSION, 26)
        self.assertIsNotNone(self.connection.execute("SELECT name FROM sqlite_master WHERE name='conversation_tool_results'").fetchone())

    def test_champion_query_follow_up_pronoun_uses_latest_tool(self) -> None:
        self._set_champion("version-1", "turtle_v5", "fingerprint123456", "2026-07-18T00:00:00Z")

        first = self.brain.respond(_request("현재 챔피언 상태 알려줘"))
        second = self.brain.respond(_request("그건 언제 선정됐어?"))

        self.assertEqual(first.tool_calls, ("champion_status",))
        self.assertEqual(second.route, "tool_follow_up")
        self.assertIn("2026-07-18T00:00:00Z", second.text)

    def test_pipeline_history_follow_up_returns_recent_run(self) -> None:
        self.connection.execute(
            "INSERT INTO gaon_v5_pipeline_runs(run_id, correlation_id, status, current_stage, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run-new", "corr", "completed", "completed", "{}", NOW, NOW),
        )

        self.brain.respond(_request("v5 파이프라인 실행 이력 알려줘"))
        follow_up = self.brain.respond(_request("그중 최근 것 알려줘"))

        self.assertEqual(follow_up.tool_calls, ("v5_pipeline_history",))
        self.assertIn("run-new", follow_up.text)

    def test_runtime_status_follow_up_rechecks_live_status(self) -> None:
        self.brain.respond(_request("가온 상태 알려줘"))
        follow_up = self.brain.respond(_request("그 상태 자세히 알려줘"))

        self.assertEqual(follow_up.tool_calls, ("runtime_status",))
        self.assertIn("Runtime", follow_up.text)

    def test_stale_tool_result_does_not_override_live_champion(self) -> None:
        self._set_champion("version-old", "old_strategy", "oldfingerprint", "2026-07-18T00:00:00Z")
        self.brain.respond(_request("현재 챔피언 상태 알려줘"))
        self.connection.execute("UPDATE champion_registry SET active_version_id=?, payload_json=?, updated_at=? WHERE slot='default'", ("version-new", '{"strategy_ref":"new_strategy","fingerprint":"newfingerprint","revision":2}', NOW))

        follow_up = self.brain.respond(_request("그건 언제 선정됐어?"))

        self.assertIn("new_strategy", follow_up.text)
        self.assertNotIn("old_strategy", follow_up.text)

    def test_ambiguous_follow_up_without_prior_tool_falls_back_safely(self) -> None:
        response = self.brain.respond(_request("그건 뭐야?"))

        self.assertEqual(response.tool_calls, ())
        self.assertNotEqual(response.route, "tool_follow_up")

    def _set_champion(self, version: str, strategy: str, fingerprint: str, updated_at: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO champion_registry(slot, active_version_id, payload_json, updated_at) VALUES (?, ?, ?, ?)",
            ("default", version, f'{{"strategy_ref":"{strategy}","fingerprint":"{fingerprint}","revision":1}}', updated_at),
        )


def _request(text: str) -> LLMConversationRequest:
    return LLMConversationRequest("session:multi-turn", "user:youngha", "test", text, NOW, f"message:{text}")


if __name__ == "__main__":
    unittest.main()
