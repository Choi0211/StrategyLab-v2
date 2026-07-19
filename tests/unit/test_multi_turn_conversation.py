import sqlite3
import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse, ProviderTimeoutError
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
        self.audit = SQLiteToolAuditRepository(self.connection)
        self.brain = self._brain()

    def tearDown(self) -> None:
        self.connection.close()

    def test_schema_migrates_to_v26(self) -> None:
        self.assertGreaterEqual(SCHEMA_VERSION, 26)
        self.assertIsNotNone(self.connection.execute("SELECT name FROM sqlite_master WHERE name='conversation_tool_results'").fetchone())

    def test_champion_query_follow_up_pronoun_uses_latest_tool(self) -> None:
        self._set_champion("version-1", "turtle_v5", "fingerprint123456", "2026-07-18T00:00:00Z")

        first = self.brain.respond(_request("현재 챔피언 상태 알려줘"))
        second = self.brain.respond(_request("그건 언제 설정됐어?"))

        self.assertEqual(first.tool_calls, ("champion_status",))
        self.assertEqual(second.route, "tool_follow_up")
        self.assertIn("2026-07-18T00:00:00Z", second.text)

    def test_pipeline_history_follow_up_returns_recent_run(self) -> None:
        self._insert_pipeline("run-new", "completed", "completed")

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

        follow_up = self.brain.respond(_request("그건 언제 설정됐어?"))

        self.assertIn("new_strategy", follow_up.text)
        self.assertNotIn("old_strategy", follow_up.text)

    def test_ambiguous_follow_up_without_prior_tool_falls_back_safely(self) -> None:
        response = self.brain.respond(_request("그건 뭐야?"))

        self.assertEqual(response.tool_calls, ())
        self.assertNotEqual(response.route, "tool_follow_up")

    def test_multi_result_synthesis_reuses_fresh_champion_and_pipeline_results(self) -> None:
        provider = _SynthesisProvider("현재 Champion과 v5 파이프라인 상태를 함께 보면 승인 대기 단계입니다, 영하님.")
        brain = self._brain(provider=provider, assistant_provider="openai-compatible")
        self._set_champion("version-1", "turtle_v5", "fingerprint123456", NOW)
        self._insert_pipeline("run-1", "completed", "promotion_approval")

        brain.respond(_request("현재 챔피언 상태 알려줘"))
        brain.respond(_request("최근 v5 파이프라인 이력 알려줘"))
        before = len(self.audit.list())
        response = brain.respond(_request("방금 알려준 챔피언과 파이프라인 상태를 종합해서 설명해줘"))

        self.assertEqual(response.route, "tool_result_synthesis")
        self.assertEqual(response.provider, "fake-synthesis")
        self.assertIn("영하님", response.text)
        self.assertEqual(len(self.audit.list()), before)
        self.assertIn("[champion_status]", provider.prompts[-1])
        self.assertIn("[v5_pipeline_history]", provider.prompts[-1])

    def test_stale_champion_result_is_refreshed_for_synthesis(self) -> None:
        brain = self._brain(provider=_SynthesisProvider("갱신된 Champion 기준으로 종합했습니다, 영하님."), assistant_provider="openai-compatible")
        self._set_champion("version-old", "old_strategy", "oldfingerprint", NOW)
        brain.respond(_request("현재 챔피언 상태 알려줘", received_at="2026-07-19T00:00:00Z"))
        self.connection.execute("UPDATE conversation_tool_results SET expires_at=? WHERE tool_name=?", ("2026-07-19T00:00:01Z", "champion_status"))
        self._insert_pipeline("run-2", "completed", "completed")
        brain.respond(_request("최근 v5 파이프라인 이력 알려줘", received_at="2026-07-19T00:00:02Z"))
        self.connection.execute("UPDATE champion_registry SET active_version_id=?, payload_json=?, updated_at=? WHERE slot='default'", ("version-new", '{"strategy_ref":"new_strategy","fingerprint":"newfingerprint","revision":2}', NOW))

        response = brain.respond(_request("챔피언과 v5 파이프라인을 같이 설명해줘", received_at="2026-07-19T00:30:00Z"))

        self.assertEqual(response.route, "tool_result_synthesis")
        self.assertGreaterEqual(len(self.audit.list(tool_name="champion_status")), 2)

    def test_missing_pipeline_result_is_called_for_synthesis(self) -> None:
        brain = self._brain(provider=_SynthesisProvider("Champion과 새 pipeline 결과를 종합했습니다, 영하님."), assistant_provider="openai-compatible")
        self._set_champion("version-1", "turtle_v5", "fingerprint123456", NOW)
        self._insert_pipeline("run-3", "completed", "completed")
        brain.respond(_request("현재 챔피언 상태 알려줘"))

        response = brain.respond(_request("챔피언과 v5 파이프라인을 같이 설명해줘"))

        self.assertEqual(response.route, "tool_result_synthesis")
        self.assertEqual(len(self.audit.list(tool_name="v5_pipeline_history")), 1)

    def test_synthesis_provider_unavailable_uses_deterministic_summary(self) -> None:
        brain = self._brain(provider=_FailingProvider(), assistant_provider="openai-compatible")
        self._set_champion("version-1", "turtle_v5", "fingerprint123456", NOW)
        self._insert_pipeline("run-4", "completed", "completed")
        brain.respond(_request("현재 챔피언 상태 알려줘"))
        brain.respond(_request("최근 v5 파이프라인 이력 알려줘"))

        response = brain.respond(_request("방금 내용 종합해줘"))

        self.assertEqual(response.route, "tool_result_synthesis")
        self.assertEqual(response.provider, "deterministic")
        self.assertIn("turtle_v5", response.text)
        self.assertNotIn("{", response.text)

    def _set_champion(self, version: str, strategy: str, fingerprint: str, updated_at: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO champion_registry(slot, active_version_id, payload_json, updated_at) VALUES (?, ?, ?, ?)",
            ("default", version, f'{{"strategy_ref":"{strategy}","fingerprint":"{fingerprint}","revision":1}}', updated_at),
        )

    def _insert_pipeline(self, run_id: str, status: str, stage: str) -> None:
        self.connection.execute(
            "INSERT INTO gaon_v5_pipeline_runs(run_id, correlation_id, status, current_stage, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, f"corr:{run_id}", status, stage, "{}", NOW, NOW),
        )

    def _brain(self, *, provider=None, assistant_provider: str = "deterministic") -> LLMConversationBrain:
        return LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider=assistant_provider),
            self.repository,
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection), self.audit),
            tool_result_repository=self.tool_results,
            assistant_provider=provider,
        )


class _SynthesisProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def respond(self, request):
        self.prompts.append(request.prompt or request.text)
        return AssistantProviderResponse(text=self.text, provider_name="fake-synthesis")


class _FailingProvider:
    def respond(self, request):
        raise ProviderTimeoutError("synthetic synthesis timeout")


def _request(text: str, *, received_at: str = NOW) -> LLMConversationRequest:
    return LLMConversationRequest("session:multi-turn", "user:youngha", "test", text, received_at, f"message:{text}:{received_at}")


if __name__ == "__main__":
    unittest.main()
