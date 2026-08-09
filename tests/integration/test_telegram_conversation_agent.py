import os
import tempfile
import unittest

from gaon.integrations.telegram.contracts import TelegramResponse
from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantToolCall
from gaon.runtime.cli import TELEGRAM_POLL_OFFSET_KEY, _failure_tool_executor, _strict_real_research_payload, main as cli_main, poll_once
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.conversational_mvp import render_single_symbol_summary
from gaon.runtime.llm_tools import SafeToolExecutor, ToolDefinition, ToolRegistry, ToolRiskLevel
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.research import autonomous_retest
from gaon.research.autonomous_retest import autonomous_retest_release_check, research_retest_history_payload, research_retest_status_payload
from gaon.research.krx_real_pipeline import RealMarketDataUnavailable
from gaon.research.multi_symbol import (
    DEFAULT_CURATED_SYMBOLS,
    PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT,
    AutonomousMultiSymbolResearchOrchestrator,
)
from gaon.research.autonomous_retest import _ReleaseCheckBacktestRunner, _ReleaseCheckProvider


class FakeTelegramClient:
    def __init__(self, updates: tuple[dict, ...]) -> None:
        self.updates = updates
        self.sent: list[tuple[str, str]] = []
        self.calls: list[int | None] = []

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        self.calls.append(offset)
        return self.updates

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


class TelegramConversationAgentTests(unittest.TestCase):
    def test_general_korean_message_uses_persistent_conversation_brain(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(10, 1, "안녕"),))
        try:
            result = poll_once(client, _config(), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual(result[0].status, "sent")
            self.assertIn("영하님", client.sent[0][1])
            messages = store.conversations.list_messages("telegram:100")
            self.assertEqual(len(messages), 2)
            self.assertEqual(store.telegram_conversations.resolve("100", now="2026-07-19T00:00:01Z").session_id, "telegram:100")
        finally:
            store.close()

    def test_repeated_poll_does_not_duplicate_telegram_reply(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(20, 2, "가온 상태 알려줘"),))
        try:
            config = _config(assistant_enabled=True)
            first = poll_once(client, config, offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)
            second = poll_once(client, config, offset=None, received_at="2026-07-19T00:00:01Z", state=store.telegram, runtime_store=store)

            self.assertEqual(first[0].status, "sent")
            self.assertEqual(second[0].status, "duplicate")
            self.assertEqual(len(client.sent), 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="runtime_status")), 1)
        finally:
            store.close()

    def test_restart_same_db_does_not_replay_old_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            first_store = RuntimeStateStore(db)
            try:
                poll_once(FakeTelegramClient((_update(30, 3, "도움말"),)), _config(), offset=None, received_at="2026-07-19T00:00:00Z", state=first_store.telegram, runtime_store=first_store)
            finally:
                first_store.close()

            second_store = RuntimeStateStore(db)
            client = FakeTelegramClient((_update(30, 3, "도움말"),))
            try:
                result = poll_once(client, _config(), offset=None, received_at="2026-07-19T00:00:01Z", state=second_store.telegram, runtime_store=second_store)

                self.assertEqual(result[0].status, "duplicate")
                self.assertEqual(client.calls[0], 31)
                self.assertEqual(client.sent, [])
                self.assertEqual(second_store.telegram.get_offset(TELEGRAM_POLL_OFFSET_KEY), 31)
            finally:
                second_store.close()

    def test_unauthorized_message_does_not_create_conversation(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(40, 4, "안녕", chat_id=999),))
        try:
            result = poll_once(client, _config(), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual(result[0].status, "unauthorized")
            self.assertEqual(store.conversations.list_messages("telegram:999"), ())
            self.assertEqual(client.sent, [])
        finally:
            store.close()

    def test_openai_compatible_tool_roundtrip_sends_telegram_response(self) -> None:
        from gaon.runtime import llm_conversation

        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(50, 5, "현재 챔피언 상태와 가온 상태를 같이 알려줘"),))
        provider = _FakeOllamaToolProvider()
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: provider
        try:
            result = poll_once(client, _config(assistant_enabled=True, assistant_provider="openai-compatible"), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual(result[0].status, "sent")
            self.assertEqual(client.sent[0][1], "챔피언과 런타임 상태를 확인했습니다, 영하님.")
            self.assertEqual(provider.calls, 2)
            self.assertEqual({record.tool_name for record in store.tool_audit.list()}, {"champion_status", "runtime_status"})
        finally:
            llm_conversation.build_assistant_provider = original
            store.close()

    def test_openai_compatible_normal_response_sends_telegram_response(self) -> None:
        from gaon.runtime import llm_conversation

        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(60, 6, "안녕하세요 가온"),))
        provider = _FakeOllamaContentProvider()
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: provider
        try:
            result = poll_once(client, _config(assistant_enabled=True, assistant_provider="openai-compatible"), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual(result[0].status, "sent")
            self.assertEqual(client.sent[0][1], "안녕하세요, 영하님. 가온입니다.")
            self.assertEqual(provider.calls, 1)
        finally:
            llm_conversation.build_assistant_provider = original
            store.close()

    def test_telegram_multi_turn_tool_result_synthesis_reuses_prior_results(self) -> None:
        from gaon.runtime import llm_conversation

        store = RuntimeStateStore(":memory:")
        store._connection.execute(
            "INSERT OR REPLACE INTO champion_registry(slot, active_version_id, payload_json, updated_at) VALUES (?, ?, ?, ?)",
            ("default", "champion-version:1", '{"strategy_ref":"turtle_v5","fingerprint":"abc123","revision":1}', "2026-07-19T00:00:00Z"),
        )
        store._connection.execute(
            "INSERT INTO gaon_v5_pipeline_runs(run_id, correlation_id, status, current_stage, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run-telegram", "corr", "completed", "promotion_approval", "{}", "2026-07-19T00:00:00Z", "2026-07-19T00:00:00Z"),
        )
        client = FakeTelegramClient(
            (
                _update(70, 7, "현재 챔피언 상태 알려줘"),
                _update(71, 8, "최근 v5 파이프라인 이력 알려줘"),
                _update(72, 9, "방금 내용 종합해서 쉽게 설명해줘"),
            )
        )
        provider = _FakeSynthesisProvider()
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: provider
        try:
            result = poll_once(client, _config(assistant_enabled=True, assistant_provider="openai-compatible"), offset=None, received_at="2026-07-19T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual([item.status for item in result], ["sent", "sent", "sent"])
            self.assertIn("종합", client.sent[-1][1])
            self.assertEqual(len(store.tool_audit.list(tool_name="champion_status")), 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="v5_pipeline_history")), 1)
            self.assertIn("[champion_status]", provider.prompts[-1])
            self.assertIn("[v5_pipeline_history]", provider.prompts[-1])
        finally:
            llm_conversation.build_assistant_provider = original
            store.close()


    def test_production_korean_real_research_request_uses_authoritative_tool_route(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_production_real_research_update(),))
        provider = _HallucinatingRealResearchProvider()
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "krx_real_research",
                "Run the read-only KRX real-research pipeline with explicit source provenance.",
                ToolRiskLevel.READ_ONLY,
                required_args=("request_text",),
                allowed_args=("symbol",),
            ),
            lambda _args: _strict_real_research_payload(),
        )
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(
                    _config(assistant_enabled=True, assistant_provider="openai-compatible"),
                    store._connection,
                    assistant_provider=provider,
                    tool_executor=SafeToolExecutor(registry, store.tool_audit),
                ),
                allowed_chat_ids=("100",),
            )
            result = process_update(parse_update_result(client.updates[0], received_at="2026-07-26T00:00:00Z"), runtime, client)

            self.assertEqual(result.status, "sent")
            self.assertEqual(provider.calls, 0)
            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            final = client.sent[0][1]
            self.assertIn("trade_count=3", final)
            self.assertIn("fixture_backed=false", final)
            self.assertIn("provider=real:yahoo-chart", final)
            self.assertIn("TESTED", final)
            self.assertIn("HYPOTHESIS", final)
            for forbidden in ("5.32%", "1.77%", "MDD 8", "거래 횟수 4", "4회", "RSI(14) 30", "RSI 30", "MA15", "MA90", "1.5x", "-3%", "5% 익절", "10일 기간"):
                self.assertNotIn(forbidden, final)
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertEqual(assistant[-1].route, "tool_read_only_authoritative")
            self.assertEqual(assistant[-1].tool_calls, ("krx_real_research",))
        finally:
            store.close()

    def test_production_korean_autonomous_retest_request_uses_retest_authoritative_route(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_production_autonomous_retest_update(),))
        provider = _HallucinatingRealResearchProvider()
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "research_retest",
                "Run autonomous retest.",
                ToolRiskLevel.READ_ONLY,
                required_args=("request_text",),
                allowed_args=("symbol",),
            ),
            lambda _args: autonomous_retest_release_check(store._connection),
        )
        registry.register(
            ToolDefinition(
                "krx_real_research",
                "Run the read-only KRX real-research pipeline with explicit source provenance.",
                ToolRiskLevel.READ_ONLY,
                required_args=("request_text",),
                allowed_args=("symbol",),
            ),
            lambda _args: _strict_real_research_payload(),
        )
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(
                    _config(assistant_enabled=True, assistant_provider="openai-compatible"),
                    store._connection,
                    assistant_provider=provider,
                    tool_executor=SafeToolExecutor(registry, store.tool_audit),
                ),
                allowed_chat_ids=("100",),
            )
            result = process_update(parse_update_result(client.updates[0], received_at="2026-07-26T00:00:00Z"), runtime, client)

            self.assertEqual(result.status, "sent")
            self.assertEqual(provider.calls, 0)
            self.assertEqual(len(store.tool_audit.list(tool_name="research_retest")), 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 0)
            final = client.sent[0][1]
            self.assertIn("[자동 재검증 결과]", final)
            self.assertIn("stop_reason=min_trades_reached", final)
            self.assertIn("trade_count=31", final)
            self.assertIn("source=real", final)
            self.assertIn("fixture_backed=false", final)
            self.assertIn("TESTED", final)
            self.assertNotIn("2026-01-02 ~ 2026-07-10", final)
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertEqual(assistant[-1].route, "tool_read_only_authoritative")
            self.assertEqual(assistant[-1].tool_calls, ("research_retest",))
        finally:
            store.close()

    def test_telegram_autonomous_retest_persists_to_runtime_db(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = os.path.join(folder, "runtime.sqlite")
            store = RuntimeStateStore(db_path)
            client = FakeTelegramClient((_production_autonomous_retest_update(),))
            try:
                result = poll_once(
                    client,
                    _config(assistant_enabled=True, assistant_provider="openai-compatible"),
                    offset=None,
                    received_at="2026-07-26T00:00:00Z",
                    state=store.telegram,
                    runtime_store=store,
                )

                self.assertEqual(result[0].status, "sent")
                self.assertEqual(store._connection.execute("SELECT COUNT(*) FROM research_retest_runs").fetchone()[0], 1)
                self.assertGreaterEqual(store._connection.execute("SELECT COUNT(*) FROM research_retest_evidence").fetchone()[0], 1)
                self.assertGreaterEqual(store._connection.execute("SELECT COUNT(*) FROM research_period_plans").fetchone()[0], 4)
                status = research_retest_status_payload(store._connection)
                history = research_retest_history_payload(store._connection)
                self.assertFalse(status["empty"])
                self.assertFalse(history["empty"])
                self.assertTrue(status["runs"][0]["run_id"].startswith("autonomous-retest:"))
                self.assertIn("strategy_fingerprint", status["runs"][0])
                self.assertIn("assumptions_fingerprint", status["runs"][0])
                self.assertIn("provider_gaps", history["evidence"][0])
                self.assertIn("blocking_findings", history["evidence"][0])
                self.assertIn("metrics", history["evidence"][0])
            finally:
                store.close()

            reopened = RuntimeStateStore(db_path)
            try:
                self.assertFalse(research_retest_status_payload(reopened._connection)["empty"])
                self.assertFalse(research_retest_history_payload(reopened._connection)["empty"])
            finally:
                reopened.close()

    def test_telegram_autonomous_retest_duplicate_message_does_not_store_second_run(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_production_autonomous_retest_update(),))
        try:
            config = _config(assistant_enabled=True, assistant_provider="openai-compatible")
            first = poll_once(client, config, offset=None, received_at="2026-07-26T00:00:00Z", state=store.telegram, runtime_store=store)
            second = poll_once(client, config, offset=None, received_at="2026-07-26T00:00:01Z", state=store.telegram, runtime_store=store)

            self.assertEqual(first[0].status, "sent")
            self.assertEqual(second[0].status, "duplicate")
            self.assertEqual(store._connection.execute("SELECT COUNT(*) FROM research_retest_runs").fetchone()[0], 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="research_retest")), 1)
        finally:
            store.close()

    def test_telegram_autonomous_retest_persistence_failure_is_not_success(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_production_autonomous_retest_update(),))
        original = autonomous_retest.SQLiteAutonomousRetestRepository.add_run

        def fail_persist(self, run):  # noqa: ANN001
            raise RuntimeError("synthetic persistence failure")

        autonomous_retest.SQLiteAutonomousRetestRepository.add_run = fail_persist
        try:
            result = poll_once(
                client,
                _config(assistant_enabled=True, assistant_provider="openai-compatible"),
                offset=None,
                received_at="2026-07-26T00:00:00Z",
                state=store.telegram,
                runtime_store=store,
            )

            self.assertEqual(result[0].status, "sent")
            self.assertIn("오류", client.sent[0][1])
            self.assertNotIn("[자동 재검증 결과]", client.sent[0][1])
            self.assertEqual(store._connection.execute("SELECT COUNT(*) FROM research_retest_runs").fetchone()[0], 0)
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertIn("failure", assistant[-1].route)
        finally:
            autonomous_retest.SQLiteAutonomousRetestRepository.add_run = original
            store.close()

    def test_production_korean_multi_symbol_request_uses_authoritative_route_and_persists(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_production_multi_symbol_update(),))
        provider = _HallucinatingRealResearchProvider()
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "multi_symbol_research",
                "Run read-only multi-symbol KRX real research.",
                ToolRiskLevel.READ_ONLY,
                required_args=("request_text",),
                allowed_args=("symbols", "universe_type", "start_date", "end_date"),
            ),
            lambda args: AutonomousMultiSymbolResearchOrchestrator(store._connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(
                str(args["request_text"]),
                symbols=tuple(args.get("symbols", DEFAULT_CURATED_SYMBOLS)),
                universe_type=str(args.get("universe_type", "explicit")),
                start_date=str(args.get("start_date", "2021-07-25")),
                end_date=str(args.get("end_date", "2026-07-24")),
            ).to_json(),
        )
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(
                    _config(assistant_enabled=True, assistant_provider="openai-compatible"),
                    store._connection,
                    assistant_provider=provider,
                    tool_executor=SafeToolExecutor(registry, store.tool_audit),
                ),
                allowed_chat_ids=("100",),
            )
            result = process_update(parse_update_result(client.updates[0], received_at="2026-07-28T00:00:00Z"), runtime, client)

            self.assertEqual(result.status, "sent")
            self.assertEqual(provider.calls, 0)
            self.assertEqual(len(store.tool_audit.list(tool_name="multi_symbol_research")), 1)
            self.assertEqual(store._connection.execute("SELECT COUNT(*) FROM multi_symbol_research_runs").fetchone()[0], 1)
            self.assertEqual(store._connection.execute("SELECT COUNT(*) FROM multi_symbol_symbol_evidence").fetchone()[0], 5)
            self.assertGreater(store._connection.execute("SELECT COUNT(*) FROM multi_symbol_candidate_evidence").fetchone()[0], 0)
            audit = store.tool_audit.list(tool_name="multi_symbol_research")[0]
            self.assertEqual(tuple(audit.request["arguments"]["symbols"]), DEFAULT_CURATED_SYMBOLS)
            self.assertEqual(audit.request["arguments"]["start_date"], "2021-07-25")
            self.assertEqual(audit.request["arguments"]["end_date"], "2026-07-24")
            final = client.sent[0][1]
            self.assertIn("[다중종목 실제 연구]", final)
            self.assertIn("aggregate_trade_count=", final)
            self.assertIn("sample_confidence=", final)
            self.assertIn("concentration=", final)
            self.assertIn("generalization=", final)
            self.assertNotIn("현재는 아직 실제 시세", final)
            self.assertNotIn("5.32%", final)
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertEqual(assistant[-1].route, "tool_read_only_authoritative")
            self.assertEqual(assistant[-1].tool_calls, ("multi_symbol_research",))
        finally:
            store.close()

    def test_production_korean_multi_symbol_duplicate_message_does_not_store_second_run(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_production_multi_symbol_update(),))
        try:
            config = _config(assistant_enabled=True, assistant_provider="openai-compatible")
            first = poll_once(client, config, offset=None, received_at="2026-07-28T00:00:00Z", state=store.telegram, runtime_store=store)
            second = poll_once(client, config, offset=None, received_at="2026-07-28T00:00:01Z", state=store.telegram, runtime_store=store)

            self.assertEqual(first[0].status, "sent")
            self.assertEqual(second[0].status, "duplicate")
            self.assertEqual(store._connection.execute("SELECT COUNT(*) FROM multi_symbol_research_runs").fetchone()[0], 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="multi_symbol_research")), 1)
        finally:
            store.close()

    def test_authoritative_market_data_failure_is_transparent_and_provider_free_form_is_blocked(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_production_real_research_update(),))
        provider = _HallucinatingRealResearchProvider()
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(
                    _config(assistant_enabled=True, assistant_provider="openai-compatible"),
                    store._connection,
                    assistant_provider=provider,
                    tool_executor=_failure_tool_executor(store, RealMarketDataUnavailable("real_data_unavailable: provider returned no usable bars")),
                ),
                allowed_chat_ids=("100",),
            )
            result = process_update(parse_update_result(client.updates[0], received_at="2026-07-26T00:00:00Z"), runtime, client)

            self.assertEqual(result.status, "sent")
            self.assertEqual(provider.calls, 0)
            final = client.sent[0][1]
            self.assertIn("실제 시장 데이터를 가져오지 못해", final)
            self.assertNotIn("로컬 LLM", final)
            self.assertNotIn("5.32%", final)
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertEqual(assistant[-1].route, "research_failure_market_data")
        finally:
            store.close()

    def test_telegram_failure_routing_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["telegram-real-research-failure-routing-release-check", "--db", ":memory:"]), 0)

    def test_sprint152_greeting_is_natural_korean_without_status_dump(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(200, 200, "안녕하세요"),))
        try:
            result = poll_once(client, _config(assistant_enabled=False), offset=None, received_at="2026-07-30T00:00:00Z", state=store.telegram, runtime_store=store)

            self.assertEqual(result[0].status, "sent")
            final = client.sent[0][1]
            self.assertIn("영하님의 AI 연구 파트너 가온", final)
            self.assertNotIn("유니", final)
            self.assertNotIn("run_id", final)
            self.assertNotIn("schema_version", final)
            self.assertEqual(store.tool_audit.list(), ())
        finally:
            store.close()

    def test_sprint152_single_symbol_analysis_is_human_readable(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(201, 201, "삼성전자 분석해줘"),))
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store)),
                allowed_chat_ids=("100",),
            )
            result = process_update(parse_update_result(client.updates[0], received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(result.status, "sent")
            final = client.sent[0][1]
            self.assertIn("삼성전자(005930)", final)
            self.assertIn("총 수익률", final)
            self.assertIn("MDD", final)
            self.assertIn("거래 수: 1회", final)
            self.assertIn("거래 표본이 1건뿐이므로", final)
            for forbidden in ("validation_id", "fixture_backed", "None", " inf", "<output>", "RealBacktestResult"):
                self.assertNotIn(forbidden, final)
            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
        finally:
            store.close()

    def test_sprint152_compare_symbols_analyzes_both_requested_symbols(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(202, 202, "삼성전자와 SK하이닉스 비교해줘"),))
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store)),
                allowed_chat_ids=("100",),
            )
            result = process_update(parse_update_result(client.updates[0], received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(result.status, "sent")
            final = client.sent[0][1]
            self.assertIn("삼성전자(005930)", final)
            self.assertIn("SK하이닉스(000660)", final)
            self.assertIn("동일 조건", final)
            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 2)
        finally:
            store.close()

    def test_sprint152_followups_use_same_chat_context_only(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(203, 203, "삼성전자 분석해줘"), _update(204, 204, "왜 그렇게 판단했어?"), _update(205, 205, "왜 그렇게 판단했어?", chat_id=101)))
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store)),
                allowed_chat_ids=("100", "101"),
            )
            for raw in client.updates:
                process_update(parse_update_result(raw, received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertIn("저장된 구조화 결과", client.sent[1][1])
            self.assertIn("직전에 설명할 분석 결과가 없습니다", client.sent[2][1])
        finally:
            store.close()

    def test_hotfix1521_followup_explains_previous_real_single_without_new_tool_call(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(240, 240, "삼성전자 분석해줘"), _update(241, 241, "왜 그렇게 판단했어?")))
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for raw in client.updates:
                process_update(parse_update_result(raw, received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            final = client.sent[1][1]
            self.assertIn("직전 삼성전자(005930) 분석 판단 근거", final)
            self.assertIn("Yahoo Chart 공개 데이터", final)
            self.assertIn("데이터 무결성 검토 통과", final)
            self.assertIn("전략 성과가 검증됐다는 뜻은 아닙니다", final)
            self.assertNotIn("fixture", final)
            self.assertNotIn("quality_status=", final)
            self.assertNotIn("source=", final)
            self.assertNotIn("champion", final.casefold())
            self.assertNotIn("v5", final.casefold())
        finally:
            store.close()

    def test_hotfix1521_compare_followups_use_both_symbols_without_unrelated_tools(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(
            (
                _update(242, 242, "삼성전자와 SK하이닉스 비교해줘"),
                _update(243, 243, "쉽게 설명해줘"),
                _update(244, 244, "자세히 보여줘"),
            )
        )
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for raw in client.updates:
                process_update(parse_update_result(raw, received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 2)
            simple = client.sent[1][1]
            detail = client.sent[2][1]
            for text in (simple, detail):
                self.assertIn("삼성전자(005930)", text)
                self.assertIn("SK하이닉스(000660)", text)
                self.assertNotIn("fixture:krx-market-data", text)
                self.assertNotIn("2026-07-01", text)
                self.assertNotIn("champion", text.casefold())
                self.assertNotIn("v5", text.casefold())
            self.assertIn("직전 비교의 상세 구조화 결과", detail)
        finally:
            store.close()

    def test_hotfix1521_greeting_preserves_previous_research_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(245, 245, "삼성전자 분석해줘"), _update(246, 246, "안녕하세요"), _update(247, 247, "왜 그렇게 판단했어?")))
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for raw in client.updates:
                process_update(parse_update_result(raw, received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            self.assertIn("직전 삼성전자(005930) 분석 판단 근거", client.sent[2][1])
        finally:
            store.close()

    def test_hotfix1521_compare_replaces_single_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(
            (
                _update(248, 248, "삼성전자 분석해줘"),
                _update(249, 249, "삼성전자와 SK하이닉스 비교해줘"),
                _update(250, 250, "왜 그렇게 판단했어?"),
            )
        )
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for raw in client.updates:
                process_update(parse_update_result(raw, received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 3)
            final = client.sent[2][1]
            self.assertIn("직전 비교 판단", final)
            self.assertIn("삼성전자(005930)", final)
            self.assertIn("SK하이닉스(000660)", final)
        finally:
            store.close()

    def test_hotfix1521_fixture_warning_is_conditional(self) -> None:
        real_text = render_single_symbol_summary(_sprint152_payload("005930", fixture_backed=False), user_text="삼성전자 분석해줘")
        fixture_text = render_single_symbol_summary(_sprint152_payload("005930", fixture_backed=True), user_text="삼성전자 분석해줘")

        self.assertNotIn("fixture 데이터 기반", real_text)
        self.assertIn("fixture 데이터 기반", fixture_text)

    def test_hotfix1521_context_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-conversation-context-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1523_result_presentation_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-result-presentation-release-check", "--db", ":memory:"]), 0)


    def test_sprint154_natural_conversation_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-natural-conversation-release-check", "--db", ":memory:"]), 0)

    def test_sprint154_telegram_presentation_followups_reuse_context_and_preferences(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        texts = (
            "삼성전자 분석해줘",
            "지금 사도 돼?",
            "한 줄로 말해줘",
            "비유해서 설명해줘",
            "예를 들어 설명해줘",
            "전문적으로 설명해줘",
            "전문용어 빼줘",
        )
        try:
            for index, text in enumerate(texts, 1):
                runtime = TelegramRuntime(
                    TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                    allowed_chat_ids=("100",),
                )
                process_update(parse_update_result(_update(540 + index, 540 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            decision = client.sent[1][1]
            one_line = client.sent[2][1]
            teaching = client.sent[3][1]
            example = client.sent[4][1]
            professional = client.sent[5][1]
            simple = client.sent[6][1]
            self.assertTrue(decision.startswith("현재 결과만으로는 매수를 추천하기 어렵습니다."))
            self.assertLessEqual(len([line for line in one_line.splitlines() if line.strip()]), 1)
            self.assertIn("시험 문제", teaching)
            self.assertIn("1,000,000원", example)
            for token in ("MDD", "Sharpe", "Profit Factor", "Exposure", "trade_count"):
                self.assertIn(token, professional)
            self.assertNotIn("quality_status=", "\n".join(item[1] for item in client.sent))
            self.assertNotIn("strategy_fingerprint", "\n".join(item[1] for item in client.sent))
            self.assertNotIn("fixture_backed", "\n".join(item[1] for item in client.sent))
            self.assertNotIn("매수하세요", "\n".join(item[1] for item in client.sent))
            self.assertIn("거래", simple)
        finally:
            store.close()

    def test_hotfix1541_presentation_state_and_grounding_integrity(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        texts = (
            "삼성전자 분석해줘",
            "지금 사도 돼?",
            "한 줄로 말해줘",
            "비유해서 설명해줘",
            "예를 들어 설명해줘",
            "전문적으로 설명해줘",
            "전문용어 빼줘",
            "조금 더 짧게",
            "자세히 보여줘",
        )
        try:
            for index, text in enumerate(texts, 1):
                runtime = TelegramRuntime(
                    TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                    allowed_chat_ids=("100",),
                )
                process_update(parse_update_result(_update(560 + index, 560 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            short = client.sent[7][1]
            detail = client.sent[8][1]
            self.assertNotIn("[결론]", short)
            self.assertLessEqual(short.count("Yahoo Chart 공개 데이터"), 1)
            self.assertIn("Yahoo Chart 공개 데이터", short)
            self.assertNotIn("명시되지", "\n".join(text for _chat_id, text in client.sent))
            self.assertNotIn("알 수 없음", "\n".join(text for _chat_id, text in client.sent))
            self.assertIn("총 수익률", detail)
            self.assertIn("MDD", detail)
            self.assertIn("Profit Factor", detail)
            self.assertIn("Yahoo Chart 공개 데이터", detail)
            self.assertGreater(len([line for line in detail.splitlines() if line.strip()]), len([line for line in short.splitlines() if line.strip()]))
            for text in (sent_text for _chat_id, sent_text in client.sent[1:]):
                self.assertNotIn("quality_status=", text)
                self.assertNotIn("fixture_backed", text)
                self.assertNotIn("strategy_fingerprint", text)
                self.assertNotIn("매수하세요", text)
        finally:
            store.close()

    def test_hotfix1541_presentation_integrity_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-presentation-integrity-release-check", "--db", ":memory:"]), 0)

    def test_sprint155_ambiguous_period_rerun_requests_clarification(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(600, 600, "삼성전자 분석해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(601, 601, "더 긴 기간으로 다시 분석해봐"), received_at="2026-07-30T00:00:01Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            self.assertIn("기간을 지정", client.sent[-1][1])
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertEqual(assistant[-1].route, "conversation_research_execution_clarification")
        finally:
            store.close()

    def test_sprint155_period_rerun_preserves_symbol_and_executes_research(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(602, 602, "삼성전자 분석해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(603, 603, "5년으로 다시 해봐"), received_at="2026-07-30T00:00:01Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="krx_real_research")
            self.assertEqual(len(audits), 2)
            args = audits[-1].request["arguments"]
            self.assertEqual(args["symbol"], "005930")
            self.assertEqual(args["start_date"], "2021-07-11")
            self.assertEqual(args["end_date"], "2026-07-10")
            final = client.sent[-1][1]
            self.assertIn("삼성전자(005930)", final)
            self.assertIn("기간: 2021-07-11 ~ 2026-07-10", final)
            self.assertIn("Yahoo Chart 공개 데이터", final)
            self.assertIn("직전 결과와 비교", final)
            self.assertNotIn("run_id", final)
            self.assertNotIn("strategy_fingerprint", final)
        finally:
            store.close()

    def test_sprint155_period_confirmation_keeps_context_after_clarification(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(604, 604, "삼성전자 분석해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(605, 605, "더 길게 다시 해봐"), received_at="2026-07-30T00:00:01Z"), runtime, client)
            process_update(parse_update_result(_update(606, 606, "3년"), received_at="2026-07-30T00:00:02Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="krx_real_research")
            self.assertEqual(len(audits), 2)
            self.assertEqual(audits[-1].request["arguments"]["symbol"], "005930")
            self.assertEqual(audits[-1].request["arguments"]["start_date"], "2023-07-11")
            self.assertIn("기간: 2023-07-11 ~ 2026-07-10", client.sent[-1][1])
        finally:
            store.close()

    def test_sprint155_multi_symbol_period_rerun_uses_multi_symbol_safe_tool(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(607, 607, "삼성전자와 SK하이닉스 비교해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(608, 608, "3년으로 다시 비교해줘"), received_at="2026-07-30T00:00:01Z"), runtime, client)

            multi_audits = store.tool_audit.list(tool_name="multi_symbol_research")
            self.assertEqual(len(multi_audits), 1)
            args = multi_audits[0].request["arguments"]
            self.assertEqual(tuple(args["symbols"]), ("005930", "000660"))
            self.assertEqual(args["start_date"], "2023-07-11")
            self.assertEqual(args["end_date"], "2026-07-10")
            final = client.sent[-1][1]
            self.assertIn("삼성전자(005930)", final)
            self.assertIn("SK하이닉스(000660)", final)
            self.assertIn("주문이나 자동 승격은 수행하지 않았습니다", final)
        finally:
            store.close()

    def test_hotfix1551_multi_symbol_evidence_schema_rerun_is_grounded(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(612, 612, "삼성전자와 SK하이닉스 비교해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(613, 613, "3년으로 다시 비교해줘"), received_at="2026-07-30T00:00:01Z"), runtime, client)

            final = client.sent[-1][1]
            self.assertEqual(store.tool_audit.list(tool_name="multi_symbol_research")[-1].request["arguments"]["start_date"], "2023-07-11")
            self.assertIn("005930", final)
            self.assertIn("000660", final)
            self.assertNotIn("unknown(unknown)", final)
            self.assertNotIn("run_id", final)
        finally:
            store.close()

    def test_hotfix1551_typo_followup_routes_to_multi_symbol_rerun(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(614, 614, "삼성전자와 sk하이닏스 비교해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(615, 615, "최근 3년으로 다시 비겨해줘"), received_at="2026-07-30T00:00:01Z"), runtime, client)

            audit = store.tool_audit.list(tool_name="multi_symbol_research")[-1]
            self.assertEqual(tuple(audit.request["arguments"]["symbols"]), ("005930", "000660"))
            self.assertEqual(audit.request["arguments"]["start_date"], "2023-07-11")
            self.assertNotIn("unknown(unknown)", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1551_quality_detail_followup_does_not_rerun(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(616, 616, "삼성전자와 SK하이닉스 비교해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(617, 617, "3년으로 다시 비교해줘"), received_at="2026-07-30T00:00:01Z"), runtime, client)
            before = len(store.tool_audit.list(tool_name="multi_symbol_research"))
            process_update(parse_update_result(_update(618, 618, "데이터 문제 자세히 보여줘"), received_at="2026-07-30T00:00:02Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="multi_symbol_research")), before)
            self.assertIn("2025-09-19", client.sent[-1][1])
            self.assertIn("다시 실행하지 않았습니다", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1551_invalid_multi_symbol_result_is_fail_closed(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False, invalid_multi_result=True)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(619, 619, "삼성전자와 SK하이닉스 비교해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(620, 620, "3년으로 다시 비교해줘"), received_at="2026-07-30T00:00:01Z"), runtime, client)

            self.assertIn("안전하게 저장된 구조화 결과로 확인하지 못했습니다", client.sent[-1][1])
            self.assertNotIn("unknown(unknown)", client.sent[-1][1])
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertEqual(assistant[-1].route, "conversation_research_execution_invalid_result")
        finally:
            store.close()

    def test_sprint155_missing_context_rerun_is_fail_closed(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(609, 609, "5년으로 다시 해봐"),))
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(client.updates[0], received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 0)
            self.assertEqual(len(store.tool_audit.list(tool_name="multi_symbol_research")), 0)
        finally:
            store.close()

    def test_sprint155_presentation_followup_does_not_rerun_research(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(610, 610, "삼성전자 분석해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(611, 611, "조금 더 짧게"), received_at="2026-07-30T00:00:01Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="multi_symbol_research")), 0)
        finally:
            store.close()

    def test_hotfix1631_autonomous_validate_routes_from_telegram_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        provider = _HallucinatingRealResearchProvider()
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(
                    _config(assistant_enabled=True, assistant_provider="openai-compatible"),
                    store._connection,
                    assistant_provider=provider,
                    tool_executor=_sprint152_tool_executor(store, fixture_backed=False),
                ),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(700, 700, "삼성전자 분석해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(701, 701, "이 전략을 근거가 충분한지 검증해줘"), received_at="2026-07-30T00:00:01Z"), runtime, client)

            self.assertEqual(provider.calls, 0)
            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 1)
            final = client.sent[-1][1]
            self.assertIn("자율 연구 검증 사이클", final)
            self.assertIn("trade_count=1", final)
            self.assertIn("source=real:yahoo-chart", final)
            self.assertIn("planner_steps=1", final)
            self.assertIn("Learning Memory", final)
            self.assertNotIn("5.32%", final)
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertEqual(assistant[-1].route, "conversation_autonomous_research_cycle")
            self.assertEqual(assistant[-1].tool_calls, ("autonomous_research_cycle",))
        finally:
            store.close()

    def test_hotfix1631_autonomous_critique_uses_prior_context_without_ids(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(702, 702, "삼성전자 분석해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(703, 703, "이 전략의 문제점을 찾아서 개선 후보까지 연구해줘"), received_at="2026-07-30T00:00:01Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 1)
            final = client.sent[-1][1]
            self.assertIn("Critic", final)
            self.assertIn("개선 후보", final)
            self.assertNotIn("전략 ID", final)
            self.assertNotIn("백테스트 결과 ID", final)
            self.assertNotIn("임의", final)
        finally:
            store.close()

    def test_hotfix1631_autonomous_learning_query_reads_same_chat_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(704, 704, "삼성전자 분석해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(705, 705, "이 전략을 검증해줘"), received_at="2026-07-30T00:00:01Z"), runtime, client)
            before = len(store.tool_audit.list(tool_name="autonomous_research_cycle"))
            process_update(parse_update_result(_update(706, 706, "지금까지 연구하면서 무엇을 배웠어?"), received_at="2026-07-30T00:00:02Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), before)
            final = client.sent[-1][1]
            self.assertIn("자율 연구에서 확인한 학습 내용", final)
            self.assertIn("evidence-backed 기록", final)
            self.assertIn("1건", final)
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertEqual(assistant[-1].route, "conversation_autonomous_learning_query")
        finally:
            store.close()

    def test_hotfix1631_autonomous_context_is_chat_isolated(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100", "101"),
            )
            process_update(parse_update_result(_update(707, 707, "삼성전자 분석해줘"), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(708, 708, "이 전략을 검증해줘"), received_at="2026-07-30T00:00:01Z"), runtime, client)
            process_update(parse_update_result(_update(709, 709, "지금까지 연구하면서 무엇을 배웠어?", chat_id=101), received_at="2026-07-30T00:00:02Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 1)
            self.assertIn("현재 저장된 검증된 학습 기록은 없습니다", client.sent[-1][1])
            self.assertNotIn("learning:test:sample", client.sent[-1][1])
        finally:
            store.close()

    def test_sprint155_conversational_research_execution_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-conversational-research-execution-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1631_telegram_autonomous_research_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-telegram-autonomous-research-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1632_learning_summary_presentation_preserves_learning_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for index, text in enumerate(("삼성전자 분석해줘", "삼성전자 전략을 더 검증해봐", "지금까지 연구하면서 무엇을 배웠어?", "쉽게 설명해줘"), 1):
                process_update(parse_update_result(_update(720 + index, 720 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 1)
            final = client.sent[-1][1]
            self.assertIn("백테스트 성과표가 아니라", final)
            self.assertIn("저장된 기록: 1건", final)
            self.assertNotIn("unknown", final.casefold())
            self.assertNotIn("trade_count=0", final)
            self.assertNotIn("총수익률 계산 불가", final)
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertIn("conversation_autonomous_presentation_simplify_previous_result", tuple(message.route for message in assistant))
        finally:
            store.close()

    def test_hotfix1632_autonomous_continuation_presentation_preserves_cycle_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for index, text in enumerate(("삼성전자 분석해줘", "삼성전자 전략을 더 검증해봐", "계속 연구해줘", "쉽게 설명해줘"), 1):
                process_update(parse_update_result(_update(730 + index, 730 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 2)
            final = client.sent[-1][1]
            self.assertIn("자율 연구 진행 상태", final)
            self.assertIn("개선 후보: 2건", final)
            self.assertNotIn("unknown", final.casefold())
            self.assertNotIn("trade_count=0", final)
            session = store.conversations.get_session("telegram:100")
            self.assertEqual(session.metadata["conversation_mvp"]["last_research_context"]["last_result_kind"], "autonomous_continuation")
        finally:
            store.close()

    def test_hotfix1632_standard_research_presentation_still_works(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for index, text in enumerate(("삼성전자 분석해줘", "전문적으로 설명해줘", "쉽게 설명해줘"), 1):
                process_update(parse_update_result(_update(740 + index, 740 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            final = client.sent[-1][1]
            self.assertIn("삼성전자", final)
            self.assertNotIn("Learning Memory", final)
            self.assertNotIn("백테스트 성과표가 아니라", final)
        finally:
            store.close()

    def test_hotfix1632_comparison_rerun_presentation_keeps_comparison_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for index, text in enumerate(("삼성전자와 SK하이닉스 비교해줘", "3년으로 다시 비교해줘", "쉽게 설명해줘"), 1):
                process_update(parse_update_result(_update(750 + index, 750 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="multi_symbol_research")), 1)
            final = client.sent[-1][1]
            self.assertIn("삼성전자", final)
            self.assertIn("SK하이닉스", final)
            self.assertNotIn("Learning Memory", final)
            self.assertNotIn("unknown(unknown)", final)
        finally:
            store.close()

    def test_hotfix1632_presentation_context_is_chat_isolated(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100", "101"),
            )
            for index, text in enumerate(("삼성전자 분석해줘", "삼성전자 전략을 더 검증해봐", "지금까지 연구하면서 무엇을 배웠어?"), 1):
                process_update(parse_update_result(_update(760 + index, 760 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(770, 770, "쉽게 설명해줘", chat_id=101), received_at="2026-07-30T00:00:01Z"), runtime, client)

            self.assertIn("직전에 설명할 분석 결과가 없습니다", client.sent[-1][1])
            self.assertNotIn("저장된 기록: 1건", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1632_autonomous_context_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-autonomous-conversation-context-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1633_continuation_reuses_parent_state_and_stops_duplicates(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for index, text in enumerate(("삼성전자 분석해줘", "삼성전자 전략을 더 검증해봐", "계속 연구해줘", "한 번 더 계속 연구해줘"), 1):
                process_update(parse_update_result(_update(780 + index, 780 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="autonomous_research_cycle")
            self.assertEqual(len(audits), 3)
            validation = next(record for record in audits if record.request["arguments"].get("mode") == "validate")
            continuations = sorted(
                (record for record in audits if record.request["arguments"].get("mode") == "continue"),
                key=lambda record: int(record.result["output"]["progression"]["continuation_count"]),
            )
            self.assertNotIn("continuation_state", validation.request["arguments"])
            self.assertEqual(len(continuations), 2)
            self.assertIn("continuation_state", continuations[0].request["arguments"])
            self.assertIn("continuation_state", continuations[1].request["arguments"])
            second = continuations[0].result["output"]["progression"]
            third = continuations[1].result["output"]["progression"]
            self.assertTrue(second["parent_cycle_id"])
            self.assertGreaterEqual(int(second["continuation_count"]), 1)
            self.assertEqual(third["progression_state"], "NO_NEW_RESEARCH_PATH")
            self.assertEqual(continuations[1].result["output"]["critic_report"]["retests"], [])
            self.assertIn("NO_NEW_RESEARCH_PATH", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1633_progress_comparison_blocks_unsupported_deltas(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for index, text in enumerate(("삼성전자 분석해줘", "삼성전자 전략을 더 검증해봐", "계속 연구해줘", "지금까지 진행한 연구가 처음 연구와 비교해서 무엇이 달라졌어?"), 1):
                process_update(parse_update_result(_update(790 + index, 790 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            final = client.sent[-1][1]
            self.assertIn("구조화된 기록 기준", final)
            self.assertIn("성과 수치 변화", final)
            self.assertIn("비용 가정", final)
            for forbidden in ("cost_assumptions", "-0.98%", "CAGR -0.735", "slippage changed", "tax changed"):
                self.assertNotIn(forbidden, final)
            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 2)
        finally:
            store.close()

    def test_hotfix1633_presentation_after_progress_comparison_preserves_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            for index, text in enumerate(("삼성전자 분석해줘", "삼성전자 전략을 더 검증해봐", "계속 연구해줘", "지금까지 진행한 연구가 처음 연구와 비교해서 무엇이 달라졌어?", "쉽게 설명해줘"), 1):
                process_update(parse_update_result(_update(800 + index, 800 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 2)
            final = client.sent[-1][1]
            self.assertIn("자율 연구 진행 상태", final)
            self.assertNotIn("unknown ~ unknown", final)
            self.assertNotIn("trade_count=0", final)
        finally:
            store.close()

    def test_hotfix1633_progression_context_is_chat_isolated(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100", "101"),
            )
            for index, text in enumerate(("삼성전자 분석해줘", "삼성전자 전략을 더 검증해봐"), 1):
                process_update(parse_update_result(_update(810 + index, 810 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(813, 813, "계속 연구해줘", chat_id=101), received_at="2026-07-30T00:00:01Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 1)
            self.assertIn("직전 연구나 전략 맥락이 없습니다", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1633_autonomous_progression_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-autonomous-research-progression-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1634_progress_comparison_preserves_root_candidate_history(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            texts = (
                "삼성전자 분석해줘",
                "삼성전자 전략을 더 검증해봐",
                "계속 연구해줘",
                "한 번 더 계속 연구해줘",
                "지금까지 진행한 연구가 처음 연구와 비교해서 무엇이 달라졌어?",
            )
            for index, text in enumerate(texts, 1):
                process_update(parse_update_result(_update(830 + index, 830 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="autonomous_research_cycle")
            self.assertEqual(len(audits), 3)
            continuations = sorted(
                (record for record in audits if record.request["arguments"].get("mode") == "continue"),
                key=lambda record: int(record.result["output"]["progression"]["continuation_count"]),
            )
            final_progression = continuations[-1].result["output"]["progression"]
            self.assertEqual(len(final_progression["historical_candidates"]), 2)
            self.assertEqual(len(final_progression["historical_tested_candidates"]), 2)
            self.assertEqual(final_progression["historical_candidates"].count("candidate_kind=robust-breakout"), 1)
            self.assertEqual(final_progression["historical_candidates"].count("candidate_kind=regime-filter"), 1)
            self.assertEqual(final_progression["historical_tested_candidates"].count("candidate_kind=robust-breakout"), 1)
            self.assertEqual(final_progression["historical_tested_candidates"].count("candidate_kind=regime-filter"), 1)
            self.assertEqual(final_progression["current_cycle_candidates"], [])
            self.assertEqual(len(final_progression["duplicate_candidates"]), 2)
            self.assertEqual(final_progression["continuation_count"], 2)
            self.assertEqual(final_progression["terminal_state"], "no_new_research_path")
            final = client.sent[-1][1]
            self.assertIn("robust-breakout", final)
            self.assertIn("regime-filter", final)
            self.assertEqual(final.count("robust-breakout"), 1)
            self.assertEqual(final.count("regime-filter"), 1)
            self.assertIn("continuation_count=2", final)
            self.assertIn("terminal_state=no_new_research_path", final)
            self.assertNotIn("cost_assumptions", final)
            self.assertNotIn("-0.98%", final)
        finally:
            store.close()

    def test_hotfix1634_autonomous_history_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-autonomous-research-history-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1635_autonomous_candidate_identity_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-autonomous-candidate-identity-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1851_combined_autonomous_learning_request_routes_to_v2(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            text = (
                "삼성전자 전략을 처음부터 다시 연구해줘. "
                "외부 연구 자료를 찾아보고, 지금까지 배운 내용과 실제 시장 데이터를 사용해서 "
                "문제점을 찾고 개선 전략 후보를 만든 뒤 검증해줘. "
                "좋은 전략 후보가 생기면 나에게 승격 승인 요청하기 전까지 진행해줘."
            )
            process_update(parse_update_result(_update(860, 860, text), received_at="2026-08-08T00:00:00Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="autonomous_learning_research")
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].request["arguments"]["symbol"], "005930")
            self.assertEqual(audits[0].result["output"]["selected_orchestration"], "autonomous_learning_v2")
            self.assertEqual(audits[0].result["output"]["promotion_status"], "requires_human_approval")
            self.assertFalse(audits[0].result["output"]["strategy_mutated"])
            self.assertFalse(audits[0].result["output"]["order_executed"])
            final = client.sent[-1][1]
            self.assertIn("Autonomous Learning V2", final)
            self.assertIn("symbol=005930", final)
            self.assertIn("requires_human_approval", final)
            self.assertIn("awaiting_human_approval", final)
            self.assertNotIn("요청을 정확히 이해하지 못했습니다", final)
            self.assertNotIn("사용 가능한 기능", final)
        finally:
            store.close()

    def test_hotfix1851_autonomous_learning_continuation_keeps_symbol(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(861, 861, "삼성전자 분석해줘"), received_at="2026-08-08T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(862, 862, "계속 연구해줘"), received_at="2026-08-08T00:00:01Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="autonomous_research_cycle")
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].request["arguments"]["symbol"], "005930")
            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_learning_research")), 0)
            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            self.assertIn("자율 연구", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1852_production_combined_request_prioritizes_v2_over_legacy_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            text = (
                "삼성전자 전략을 처음부터 다시 연구해줘.\n"
                "외부 연구 자료도 찾아보고,\n"
                "지금까지 배운 내용과 실제 시장 데이터를 사용해서\n"
                "문제점을 찾고 개선 전략 후보를 만든 뒤 검증해줘.\n"
                "좋은 전략 후보가 생기면 승격 승인을 요청하기 전까지 진행해줘."
            )
            process_update(parse_update_result(_update(868, 868, "삼성전자 분석해줘"), received_at="2026-08-08T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(869, 869, text), received_at="2026-08-08T00:00:01Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="autonomous_learning_research")
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].request["arguments"]["symbol"], "005930")
            self.assertEqual(audits[0].request["arguments"]["mode"], "approval_review")
            self.assertEqual(audits[0].result["output"]["selected_orchestration"], "autonomous_learning_v2")
            self.assertEqual(len(store.tool_audit.list(tool_name="research_retest")), 0)
            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 0)
            final = client.sent[-1][1]
            self.assertIn("Autonomous Learning V2", final)
            self.assertIn("외부 연구 실행", final)
            self.assertIn("requires_human_approval", final)
            self.assertNotIn("adequacy_status", final)
            self.assertNotIn("planner_steps", final)
            self.assertNotIn("historical_TESTED_candidates", final)
            self.assertNotIn("robust-breakout", final)
            self.assertNotIn("regime-filter", final)
            assistant = [message for message in store.conversations.list_messages("telegram:100") if message.role == "assistant"]
            self.assertEqual(assistant[-1].tool_calls, ("autonomous_learning_research",))
        finally:
            store.close()

    def test_hotfix1852_v2_context_continuation_keeps_v2(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(870, 870, "삼성전자 전략 연구해줘"), received_at="2026-08-08T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(871, 871, "계속 연구해줘"), received_at="2026-08-08T00:00:01Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="autonomous_learning_research")
            self.assertEqual(len(audits), 2)
            self.assertEqual(audits[-1].request["arguments"]["symbol"], "005930")
            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_research_cycle")), 0)
            self.assertIn("Autonomous Learning V2", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1851_external_research_continuation_keeps_current_target(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(866, 866, "삼성전자 분석해줘"), received_at="2026-08-08T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(867, 867, "외부 연구 자료를 더 찾아서 검증해줘"), received_at="2026-08-08T00:00:01Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="autonomous_learning_research")
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].request["arguments"]["symbol"], "005930")
            self.assertEqual(audits[0].request["arguments"]["mode"], "external_research")
            self.assertIn("외부 연구 실행", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1851_autonomous_learning_missing_context_asks_target(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(863, 863, "계속 연구해줘"), received_at="2026-08-08T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_learning_research")), 0)
            self.assertIn("종목", client.sent[-1][1])
            self.assertIn("삼성전자", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1851_approval_sounding_phrase_does_not_mutate(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(864, 864, "삼성전자 전략 연구해줘"), received_at="2026-08-08T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(865, 865, "좋으면 알아서 적용해"), received_at="2026-08-08T00:00:01Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="autonomous_learning_research")
            self.assertEqual(len(audits), 2)
            final_output = audits[-1].result["output"]
            self.assertTrue(final_output["approval_required"])
            self.assertFalse(final_output["strategy_mutated"])
            self.assertFalse(final_output["order_executed"])
            self.assertFalse(final_output["broker_order_called"])
            self.assertFalse(final_output["kis_order_called"])
            self.assertIn("명시적인 후보별 승인", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1851_telegram_autonomous_learning_routing_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-telegram-autonomous-learning-routing-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1852_telegram_autonomous_learning_priority_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-telegram-autonomous-learning-priority-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1853_promotion_candidate_detail_followup_preserves_evidence_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            initial = (
                "삼성전자 전략을 처음부터 다시 연구해줘. 외부 연구 자료도 찾아보고 "
                "지금까지 배운 내용과 실제 시장 데이터를 사용해서 개선 전략 후보를 만든 뒤 검증해줘. "
                "좋은 전략 후보가 생기면 승격 승인을 요청하기 전까지 진행해줘."
            )
            detail = (
                "아직 승인하지 않을게. 지금 생성한 승격 후보를 자세히 설명해줘. "
                "후보 ID와 fingerprint, 기존 전략에서 무엇이 바뀌었는지, 연구 가설, "
                "참고한 외부 자료와 출처, 실제 백테스트 결과, 검증 결과, 랭킹 근거, 주요 위험을 보여줘. "
                "근거가 없는 숫자는 만들지 말고 승인이나 전략 변경도 하지 마."
            )
            process_update(parse_update_result(_update(880, 880, initial), received_at="2026-08-08T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(881, 881, detail), received_at="2026-08-08T00:00:01Z"), runtime, client)

            audits = store.tool_audit.list(tool_name="autonomous_learning_research")
            self.assertEqual(len(audits), 1)
            final = client.sent[-1][1]
            self.assertIn("[승격 후보]", final)
            self.assertIn("promotion-candidate:test-1853", final)
            self.assertIn("candidate-fingerprint-1853", final)
            self.assertIn("strategy-experiment:test-1853", final)
            self.assertIn("validation-evidence:test-1853", final)
            self.assertIn("backtest:test-1853", final)
            self.assertIn("Fixture research", final)
            self.assertIn("claim:test-1853", final)
            self.assertIn("trade_count: 60", final)
            self.assertIn("total_return: 0.18", final)
            self.assertIn("MDD: 0.09", final)
            self.assertIn("Profit Factor: 1.6", final)
            self.assertIn("requires_human_approval", final)
            self.assertIn("awaiting_human_approval", final)
            self.assertNotIn("trade_count: 0", final)
            self.assertNotIn("unknown ~ unknown", final)
            self.assertNotIn("external_research_state=", final)
            output = audits[0].result["output"]
            self.assertFalse(output["strategy_mutated"])
            self.assertFalse(output["order_executed"])
            self.assertFalse(output["broker_order_called"])
            self.assertFalse(output["kis_order_called"])
        finally:
            store.close()

    def test_hotfix1853_missing_metric_and_metadata_only_source_are_not_fabricated(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(
                    _config(assistant_enabled=True),
                    store._connection,
                    tool_executor=_sprint152_tool_executor(
                        store,
                        fixture_backed=False,
                        autonomous_learning_missing_profit_factor=True,
                        autonomous_learning_metadata_only_source=True,
                    ),
                ),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(_update(882, 882, "삼성전자 전략 연구해줘"), received_at="2026-08-08T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(883, 883, "승격 후보 자세히 보여줘. Profit Factor와 참고 자료 출처도 알려줘."), received_at="2026-08-08T00:00:01Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_learning_research")), 1)
            final = client.sent[-1][1]
            self.assertIn("Profit Factor: 확인된 구조화 결과 없음", final)
            self.assertNotIn("Profit Factor: 0", final)
            self.assertIn("metadata_only", final)
            self.assertIn("메타데이터까지만 확보", final)
        finally:
            store.close()

    def test_hotfix1853_promotion_candidate_context_is_chat_isolated(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100", "101"),
            )
            process_update(parse_update_result(_update(884, 884, "삼성전자 전략 연구해줘", chat_id=100), received_at="2026-08-08T00:00:00Z"), runtime, client)
            process_update(parse_update_result(_update(885, 885, "승격 후보 자세히 보여줘", chat_id=101), received_at="2026-08-08T00:00:01Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="autonomous_learning_research")), 1)
            self.assertIn("직전", client.sent[-1][1])
            self.assertNotIn("promotion-candidate:test-1853", client.sent[-1][1])
        finally:
            store.close()

    def test_hotfix1853_promotion_candidate_presentation_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-promotion-candidate-presentation-release-check", "--db", ":memory:"]), 0)

    def test_sprint153_conversational_reasoning_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-conversational-reasoning-release-check", "--db", ":memory:"]), 0)

    def test_sprint153_telegram_reasoning_followups_reuse_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        texts = (
            "삼성전자 분석해줘",
            "그럼 지금 사도 돼?",
            "왜?",
            "쉽게 설명해줘",
            "전문적으로 설명해줘",
            "위험은 어느 정도야?",
            "자세히 보여줘",
        )
        try:
            for index, text in enumerate(texts, 1):
                runtime = TelegramRuntime(
                    TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                    allowed_chat_ids=("100",),
                )
                process_update(parse_update_result(_update(360 + index, 360 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 1)
            decision = client.sent[1][1]
            professional = client.sent[4][1]
            risk = client.sent[5][1]
            for text in client.sent[1:]:
                final = text[1]
                self.assertIn("삼성전자", final)
                self.assertNotIn("quality_status=", final)
                self.assertNotIn("source=", final)
                self.assertNotIn("strategy_fingerprint", final)
                self.assertNotIn("validation_id", final)
            self.assertIn("매수", decision)
            self.assertIn("어렵", decision)
            self.assertIn("거래 표본", decision)
            self.assertIn("Sharpe", professional)
            self.assertIn("Profit Factor", professional)
            self.assertIn("Exposure", professional)
            self.assertIn("MDD", risk)
        finally:
            store.close()

    def test_sprint153_missing_context_risk_followup_is_deterministic(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(390, 390, "그럼 위험은?"),))
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(client.updates[0], received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertIn("직전에 설명할 분석 결과가 없습니다", client.sent[0][1])
            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 0)
        finally:
            store.close()

    def test_sprint152_partial_compare_failure_is_fail_closed(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient((_update(206, 206, "삼성전자와 SK하이닉스 비교해줘"),))
        try:
            runtime = TelegramRuntime(
                TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fail_symbol="000660")),
                allowed_chat_ids=("100",),
            )
            process_update(parse_update_result(client.updates[0], received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertIn("일부 종목 연구가 실패했습니다", client.sent[0][1])
            self.assertIn("성공한 종목만으로 우열을 만들지 않겠습니다", client.sent[0][1])
        finally:
            store.close()

    def test_sprint152_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-conversation-release-check", "--db", ":memory:"]), 0)

    def test_hotfix1522_followup_context_persists_across_runtime_recreation(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        texts = (
            "삼성전자와 sk하이닉스 비교해줘",
            "왜 그절? 판간했어?",
            "왜 그렇게 판단했어?",
            "쉽게 설명해줘",
            "자세히 보여줘",
        )
        try:
            for index, text in enumerate(texts, 1):
                runtime = TelegramRuntime(
                    TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False, zero_trade_symbols=("000660",))),
                    allowed_chat_ids=("100",),
                )
                process_update(parse_update_result(_update(300 + index, 300 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 2)
            for text in (sent_text for _chat_id, sent_text in client.sent[1:]):
                self.assertIn("삼성전자(005930)", text)
                self.assertIn("SK하이닉스(000660)", text)
                self.assertNotIn("직전 연구/비교 결과가 없습니다", text)
                for forbidden in ("champion", "v5", "fixture", "19.23", "시장 조건", "outperforms"):
                    self.assertNotIn(forbidden, text.casefold())
            self.assertIn("거래 0회", "\n".join(text for _chat_id, text in client.sent))
            session = store.conversations.get_session("telegram:100")
            metadata = session.metadata["conversation_mvp"]
            self.assertEqual(metadata["last_research_context"]["last_result_kind"], "symbol_comparison")
        finally:
            store.close()

    def test_hotfix1522_unknown_and_help_do_not_erase_persisted_research_context(self) -> None:
        store = RuntimeStateStore(":memory:")
        client = FakeTelegramClient(())
        texts = (
            "삼성전자와 SK하이닉스 비교해줘",
            "무슨말인지 모르겠네",
            "도움말",
            "왜 그렇게 판단했어?",
        )
        try:
            for index, text in enumerate(texts, 1):
                runtime = TelegramRuntime(
                    TelegramConversationAgent(_config(assistant_enabled=True), store._connection, tool_executor=_sprint152_tool_executor(store, fixture_backed=False)),
                    allowed_chat_ids=("100",),
                )
                process_update(parse_update_result(_update(320 + index, 320 + index, text), received_at="2026-07-30T00:00:00Z"), runtime, client)

            self.assertEqual(len(store.tool_audit.list(tool_name="krx_real_research")), 2)
            final = client.sent[-1][1]
            self.assertIn("삼성전자(005930)", final)
            self.assertIn("SK하이닉스(000660)", final)
            self.assertNotIn("직전 연구/비교 결과가 없습니다", final)
        finally:
            store.close()

    def test_hotfix1522_telegram_followup_release_check_passes(self) -> None:
        self.assertEqual(cli_main(["gaon-telegram-followup-release-check", "--db", ":memory:"]), 0)


class _FakeOllamaToolProvider:
    def __init__(self) -> None:
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        if not request.tool_results:
            return AssistantProviderResponse(
                text="",
                provider_name="openai-compatible",
                tool_calls=(
                    AssistantToolCall("call-champion", "champion_status", {"slot": "default"}),
                    AssistantToolCall("call-runtime", "runtime_status", {}),
                ),
            )
        return AssistantProviderResponse(text="챔피언과 런타임 상태를 확인했습니다, 영하님.", provider_name="openai-compatible")


class _FakeOllamaContentProvider:
    def __init__(self) -> None:
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        return AssistantProviderResponse(text="안녕하세요, 영하님. 가온입니다.", provider_name="openai-compatible")

class _FakeSynthesisProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def respond(self, request):
        self.prompts.append(request.prompt or request.text)
        return AssistantProviderResponse(text="챔피언과 v5 파이프라인 상태를 종합했습니다, 영하님.", provider_name="openai-compatible")


class _HallucinatingRealResearchProvider:
    def __init__(self) -> None:
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        return AssistantProviderResponse(
            text=(
                "총 수익률 5.32%, 10일 기간, 평균 거래 수익률 1.77%, MDD 8%, PF 1.42, 거래 횟수 4회입니다. "
                "동시에 10일간 단 1회 청산했고 -3% 손절, 5% 익절, RSI(14) 30, MA15/MA90, 거래량 평균 * 1.5를 추천합니다."
            ),
            provider_name="openai-compatible",
        )


def _sprint152_tool_executor(
    store: RuntimeStateStore,
    *,
    fail_symbol: str | None = None,
    fixture_backed: bool = True,
    zero_trade_symbols: tuple[str, ...] = (),
    invalid_multi_result: bool = False,
    autonomous_learning_missing_profit_factor: bool = False,
    autonomous_learning_metadata_only_source: bool = False,
) -> SafeToolExecutor:
    registry = ToolRegistry()

    def handle(args):
        symbol = str(args.get("symbol", "005930"))
        if fail_symbol == symbol:
            raise RealMarketDataUnavailable(f"real_data_unavailable: synthetic failure for {symbol}")
        return _sprint152_payload(
            symbol,
            fixture_backed=fixture_backed,
            zero_trade_symbols=zero_trade_symbols,
            start_date=str(args.get("start_date", "2026-01-02")),
            end_date=str(args.get("end_date", "2026-07-10")),
            request_text=str(args.get("request_text", "")),
        )

    def handle_multi(args):
        if invalid_multi_result:
            return {"schema_version": 36, "evidence": [{"symbol": "unknown", "metrics": {}}], "aggregate": {}}
        symbols = tuple(str(item) for item in args.get("symbols", ("005930", "000660")))
        start_date = str(args.get("start_date", "2021-07-25"))
        end_date = str(args.get("end_date", "2026-07-24"))
        outputs = [
            _sprint152_payload(symbol, fixture_backed=fixture_backed, zero_trade_symbols=zero_trade_symbols, start_date=start_date, end_date=end_date, request_text=str(args.get("request_text", "")))
            for symbol in symbols
        ]
        aggregate_trade_count = sum(int(output["backtest"]["metrics"]["trade_count"]) for output in outputs)
        return {
            "schema_version": 36,
            "run_id": "test:multi-symbol",
            "request_text": str(args.get("request_text", "")),
            "request": {
                "request_text": str(args.get("request_text", "")),
                "start_date": start_date,
                "end_date": end_date,
                "source": "real:yahoo-chart" if not fixture_backed else "fixture:sprint152",
                "fixture_backed": fixture_backed,
            },
            "evidence": [
                {
                    "evidence_id": f"test:evidence:{output['dataset']['symbols'][0]['symbol']}",
                    "symbol": output["dataset"]["symbols"][0]["symbol"],
                    "eligible": True,
                    "source": "real:yahoo-chart" if not fixture_backed else "fixture:sprint152",
                    "fixture_backed": fixture_backed,
                    "provider": "real:yahoo-chart" if not fixture_backed else "fixture:sprint152",
                    "metrics": dict(output["backtest"]["metrics"]),
                    "quality_status": output["quality"]["status"],
                    "provider_gap_dates": ["2025-09-19"] if output["dataset"]["symbols"][0]["symbol"] == "005930" else [],
                    "provider_ohlc_anomaly_dates": [],
                    "provider_zero_volume_anomaly_dates": [],
                    "blocking_findings": [],
                    "warnings": [],
                }
                for output in outputs
            ],
            "summary": {"aggregate_trade_count": aggregate_trade_count, "sample_confidence": "medium"},
            "aggregate": {"aggregate_trade_count": aggregate_trade_count, "sample_confidence": "medium"},
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
        }

    def handle_autonomous(args):
        symbol = str(args.get("symbol", "005930"))
        state = args.get("continuation_state") if isinstance(args.get("continuation_state"), dict) else None
        return _sprint163_autonomous_payload(symbol, mode=str(args.get("mode", "validate")), continuation_state=state)

    def handle_autonomous_learning(args):
        return _sprint185_autonomous_learning_payload(
            str(args.get("symbol", "005930")),
            mode=str(args.get("mode", "research")),
            request_text=str(args.get("request_text", "")),
            include_profit_factor=not autonomous_learning_missing_profit_factor,
            metadata_only_source=autonomous_learning_metadata_only_source,
        )

    registry.register(
        ToolDefinition(
            "krx_real_research",
            "Run the read-only KRX real-research pipeline with explicit source provenance.",
            ToolRiskLevel.READ_ONLY,
            required_args=("request_text",),
            allowed_args=("symbol", "start_date", "end_date"),
        ),
        handle,
    )
    registry.register(
        ToolDefinition(
            "multi_symbol_research",
            "Run deterministic multi-symbol research for conversation tests.",
            ToolRiskLevel.READ_ONLY,
            required_args=("request_text",),
            allowed_args=("symbols", "universe_type", "start_date", "end_date"),
        ),
        handle_multi,
    )
    registry.register(
        ToolDefinition(
            "autonomous_research_cycle",
            "Run deterministic autonomous research cycle for conversation tests.",
            ToolRiskLevel.READ_ONLY,
            required_args=("request_text",),
            allowed_args=("symbol", "mode", "continuation_state"),
        ),
        handle_autonomous,
    )
    registry.register(
        ToolDefinition(
            "autonomous_learning_research",
            "Run deterministic autonomous learning V2 route for conversation tests.",
            ToolRiskLevel.READ_ONLY,
            required_args=("request_text",),
            allowed_args=("symbol", "mode"),
        ),
        handle_autonomous_learning,
    )
    return SafeToolExecutor(registry, store.tool_audit)


def _sprint163_autonomous_payload(symbol: str = "005930", *, mode: str = "validate", continuation_state: dict[str, object] | None = None) -> dict[str, object]:
    baseline = _sprint152_payload(symbol, fixture_backed=False, request_text="telegram autonomous research")
    prior_tested = set(str(item) for item in (continuation_state or {}).get("tested_candidate_keys", ()) if item)
    candidate_keys = {
        "candidate_kind=robust-breakout|changed_rules=[]|hypothesis=|status=tested",
        "candidate_kind=regime-filter|changed_rules=[]|hypothesis=|status=tested",
    }
    candidate_identities = {
        "candidate_kind=robust-breakout",
        "candidate_kind=regime-filter",
    }
    duplicate = mode == "continue" and candidate_keys.issubset(prior_tested)
    retests = [] if duplicate else [
        {"candidate_id": "candidate:robust-breakout", "status": "tested", "trade_count": 4, "metrics": {"trade_count": 4}},
        {"candidate_id": "candidate:regime-filter", "status": "tested", "trade_count": 5, "metrics": {"trade_count": 5}},
    ]
    proposals = [] if duplicate else [
        {"proposal_id": "candidate:robust-breakout", "hypothesis": "robust breakout retest"},
        {"proposal_id": "candidate:regime-filter", "hypothesis": "regime filter retest"},
    ]
    terminal = "no_new_research_path" if duplicate else "needs_more_evidence"
    return {
        "schema_version": 36,
        "tool": "autonomous_research_cycle",
        "mode": mode,
        "run_id": f"autonomous-cycle:test:{mode}:{symbol}",
        "symbol": symbol,
        "baseline": baseline,
        "assessment": {
            "status": "insufficient_sample",
            "adequacy": {"trade_count": baseline["backtest"]["metrics"]["trade_count"], "observation_days": 378},
            "needs": [{"kind": "period_expansion", "reason": "trade_count below confidence threshold"}],
        },
        "plan": {"steps": [{"step_id": "step:1", "kind": "extend_period", "status": "planned"}]},
        "critic_report": {
            "findings": [{"category": "sample_size", "severity": "warning", "message": "표본 수가 아직 충분하지 않습니다."}],
            "proposals": proposals,
            "retests": retests,
        },
        "learning_report": {"stored_records": ["learning:test:sample"], "duplicate_candidates": []},
        "terminal_state": terminal,
        "autonomous_cycle": {
            "assessment": {"status": "insufficient_sample"},
            "plan": {"steps": [{"step_id": "step:1", "kind": "extend_period", "status": "planned"}]},
            "critic_report": {
                "findings": [{"category": "sample_size", "severity": "warning", "message": "표본 수가 아직 충분하지 않습니다."}],
                "proposals": [{"proposal_id": "candidate:robust-breakout"}, {"proposal_id": "candidate:regime-filter"}] if not duplicate else [],
                "retests": [
                    {"candidate_id": "candidate:robust-breakout", "status": "tested", "trade_count": 4},
                    {"candidate_id": "candidate:regime-filter", "status": "tested", "trade_count": 5},
                ] if not duplicate else [],
            },
            "learning_report": {"stored_records": ["learning:test:sample"], "duplicate_candidates": []},
            "terminal_state": terminal,
        },
        "progression": {
            "parent_cycle_id": (continuation_state or {}).get("current_cycle_id"),
            "current_cycle_id": f"autonomous-cycle:test:{mode}:{symbol}",
            "root_cycle_id": (continuation_state or {}).get("root_cycle_id") or (continuation_state or {}).get("current_cycle_id") or f"autonomous-cycle:test:{mode}:{symbol}",
            "continuation_count": int((continuation_state or {}).get("continuation_count", 0) or 0) + (1 if mode == "continue" else 0),
            "historical_candidates": sorted(set(str(item) for item in (continuation_state or {}).get("historical_candidates", ()) if item) | (set() if duplicate else candidate_identities)),
            "historical_tested_candidates": sorted(set(str(item) for item in (continuation_state or {}).get("historical_tested_candidates", ()) if item) | (set() if duplicate else candidate_identities)),
            "current_cycle_candidates": [] if duplicate else sorted(candidate_identities),
            "current_cycle_tested_candidates": [] if duplicate else sorted(candidate_identities),
            "duplicate_candidates": sorted(candidate_identities) if duplicate else [],
            "tested_candidate_keys": sorted(prior_tested | (set() if duplicate else candidate_keys)),
            "duplicate_candidate_keys": sorted(candidate_keys) if duplicate else [],
            "terminal_state": terminal,
            "progression_state": "NO_NEW_RESEARCH_PATH" if duplicate else ("CONTINUED" if mode == "continue" else "NEEDS_MORE_EVIDENCE"),
            "assumptions_immutable": True,
        },
        "source": "real:yahoo-chart",
        "fixture_backed": False,
        "quality_status": "pass_with_warnings",
        "audit": {
            "resolved_intent": f"autonomous_{mode}",
            "resolved_context_kind": "telegram_authoritative_context",
            "autonomous_cycle_invoked": True,
            "planner_invoked": True,
            "critic_invoked": True,
            "candidate_count": len(proposals),
            "retest_count": len(retests),
            "duplicate_candidate_count": 1 if duplicate else 0,
            "learning_memory_write": True,
            "learning_memory_read": mode == "learning_query",
            "terminal_state": terminal,
            "safety_state": "read_only",
        },
        "automatic_order": False,
        "automatic_champion_promotion": False,
        "automatic_config_apply": False,
    }


def _sprint185_autonomous_learning_payload(symbol: str = "005930", *, mode: str = "research", request_text: str = "", include_profit_factor: bool = True, metadata_only_source: bool = False) -> dict[str, object]:
    baseline = _sprint152_payload(symbol, fixture_backed=False, request_text=request_text)
    context = _sprint185_promotion_candidate_context(symbol, include_profit_factor=include_profit_factor, metadata_only_source=metadata_only_source)
    return {
        "schema_version": 1,
        "tool": "autonomous_learning_research",
        "mode": mode,
        "symbol": symbol,
        "request_text": request_text,
        "baseline": baseline,
        "autonomous_learning_v2": {
            "schema_version": 1,
            "external_research_state": "evidence_sufficient",
            "claims": 1,
            "hypothesis_status": "proposed",
            "validation_status": "accepted_for_review",
            "ranking_status": "ranked",
            "promotion_status": "requires_human_approval",
            "human_gate_status": "awaiting_human_approval",
            "promotion_candidate_context": context,
            "safety": "pass",
        },
        "selected_orchestration": "autonomous_learning_v2",
        "source": "real:yahoo-chart",
        "fixture_backed": False,
        "quality_status": "pass",
        "approval_required": True,
        "promotion_status": "requires_human_approval",
        "human_gate_status": "awaiting_human_approval",
        "strategy_mutated": False,
        "order_executed": False,
        "broker_order_called": False,
        "kis_order_called": False,
        "automatic_champion_promotion": False,
        "automatic_config_apply": False,
        "safety": "pass",
    }


def _sprint185_promotion_candidate_context(symbol: str = "005930", *, include_profit_factor: bool = True, metadata_only_source: bool = False) -> dict[str, object]:
    metrics: dict[str, object] = {
        "trade_count": 60,
        "total_return": 0.18,
        "mdd": 0.09,
        "win_rate": 0.56,
        "cagr": 0.035,
        "sharpe": 0.72,
    }
    if include_profit_factor:
        metrics["profit_factor"] = 1.6
    return {
        "candidate_id": "promotion-candidate:test-1853",
        "candidate_fingerprint": "candidate-fingerprint-1853",
        "baseline_strategy_id": "strategy:baseline",
        "baseline_fingerprint": f"strategy:{symbol}",
        "hypothesis": {
            "hypothesis_id": "strategy-hypothesis:test-1853",
            "topic_key": "strategy.breakout.robustness",
            "changed_rules": ["add regime filter before breakout entries"],
            "rationale": "External evidence indicates robustness depends on regime context.",
            "mechanism": "A regime filter constrains entries before validation.",
            "falsification_criteria": ["Reject if authoritative backtest metrics do not support robustness."],
            "claim_ids": ["claim:test-1853"],
        },
        "changed_rules": ["add regime filter before breakout entries"],
        "rationale": "External evidence indicates robustness depends on regime context.",
        "expected_mechanism": "A regime filter constrains entries before validation.",
        "falsification_criteria": ["Reject if authoritative backtest metrics do not support robustness."],
        "research_memory": {
            "memory_id": "external-research-memory:test-1853",
            "claim_ids": ["claim:test-1853"],
            "source_ids": ["source:test-1853"],
        },
        "claim_ids": ["claim:test-1853"],
        "source_ids": ["source:test-1853"],
        "source_lineage": [
            {
                "title": "Fixture research",
                "source_type": "research_report",
                "locator": "https://example.org/research.html",
                "source_ids": ["source:test-1853"],
                "claim_ids": ["claim:test-1853"],
                "metadata_only": metadata_only_source,
                "content_acquired": not metadata_only_source,
            }
        ],
        "experiment": {
            "experiment_id": "strategy-experiment:test-1853",
            "baseline_strategy_id": "strategy:baseline",
            "baseline_strategy_fingerprint": f"strategy:{symbol}",
            "assumptions_fingerprint": "assumptions-fingerprint-1853",
            "changed_rules": ["add regime filter before breakout entries"],
            "universe_symbols": [symbol],
            "start": "2021-07-25",
            "end": "2026-07-24",
            "cost_model": "default_research_costs",
            "status": "ready_for_validation",
        },
        "experiment_id": "strategy-experiment:test-1853",
        "experiment_fingerprint": "experiment-fingerprint-1853",
        "assumptions_fingerprint": "assumptions-fingerprint-1853",
        "authoritative_validation_evidence": {
            "evidence_id": "validation-evidence:test-1853",
            "experiment_id": "strategy-experiment:test-1853",
            "backtest_result_id": "backtest:test-1853",
            "source": "real:yahoo-chart",
            "fixture_backed": False,
            "quality_status": "pass",
            "blocking_findings": [],
            "metrics": metrics,
            "trade_count": metrics["trade_count"],
        },
        "validation": {
            "status": "accepted_for_review",
            "confidence": "high",
            "warnings": ["fixture-backed rankings are not production approval"],
        },
        "ranking": {
            "status": "ranked",
            "ranked": [
                {
                    "rank": 1,
                    "experiment_id": "strategy-experiment:test-1853",
                    "evidence_id": "validation-evidence:test-1853",
                    "score": 4.2,
                    "trade_count": metrics["trade_count"],
                    "total_return": metrics["total_return"],
                    "mdd": metrics["mdd"],
                    "profit_factor": metrics.get("profit_factor"),
                    "win_rate": metrics["win_rate"],
                    "source": "real:yahoo-chart",
                    "fixture_backed": False,
                }
            ],
            "warnings": ["fixture-backed rankings are not production approval"],
        },
        "ranking_components": {
            "score": 4.2,
            "trade_count": metrics["trade_count"],
            "total_return": metrics["total_return"],
            "mdd": metrics["mdd"],
            "profit_factor": metrics.get("profit_factor"),
            "win_rate": metrics["win_rate"],
            "source": "real:yahoo-chart",
            "fixture_backed": False,
        },
        "promotion_candidate": {
            "candidate_id": "promotion-candidate:test-1853",
            "experiment_id": "strategy-experiment:test-1853",
            "evidence_id": "validation-evidence:test-1853",
            "score": 4.2,
            "rank": 1,
            "source": "real:yahoo-chart",
            "fixture_backed": False,
            "approval_required": True,
            "rollback_target": "strategy-config:default:active",
            "status": "requires_human_approval",
            "blockers": [],
        },
        "risks": ["fixture-backed rankings are not production approval"],
        "human_gate": {
            "candidate_id": "promotion-candidate:test-1853",
            "status": "awaiting_human_approval",
            "blockers": ["missing_approval"],
            "approval": None,
        },
        "approval_state": "awaiting_human_approval",
        "strategy_mutated": False,
        "order_executed": False,
        "broker_order_called": False,
        "kis_order_called": False,
    }


def _sprint152_payload(symbol: str, *, fixture_backed: bool = True, zero_trade_symbols: tuple[str, ...] = (), start_date: str = "2026-01-02", end_date: str = "2026-07-10", request_text: str = "") -> dict[str, object]:
    trades = {"005930": 1, "000660": 7}.get(symbol, 3)
    total_return = {"005930": 0.0123, "000660": 0.061}.get(symbol, 0.02)
    mdd = {"005930": 0.044, "000660": 0.091}.get(symbol, 0.05)
    profit_factor = "inf" if symbol == "005930" else 1.42
    win_rate = 1.0 if symbol == "005930" else 0.571429
    expectancy = 0.01
    exposure = 0.2
    if symbol in zero_trade_symbols:
        trades = 0
        total_return = 0.0
        mdd = 0.0
        profit_factor = None
        win_rate = 0.0
        expectancy = 0.0
        exposure = 0.0
    return {
        "schema_version": 33,
        "dataset": {
            "symbols": [{"symbol": symbol, "name": symbol}],
            "metadata": {
                "source": "fixture:sprint152" if fixture_backed else "real:yahoo-chart",
                "market": "KOSPI",
                "timeframe": "daily",
                "start_date": start_date,
                "end_date": end_date,
                "fixture_backed": fixture_backed,
            },
        },
        "quality": {"status": "pass", "findings": []},
        "strategy": {"fingerprint": f"strategy:{symbol}"},
        "assumptions": {"initial_capital": {"value": 1000000.0, "provenance": "test"}},
        "backtest": {
            "result_id": f"backtest:{symbol}",
            "metrics": {
                "total_return": total_return,
                "mdd": mdd,
                "trade_count": trades,
                "profit_factor": profit_factor,
                "win_rate": win_rate,
                "cagr": total_return,
                "sharpe": 0.42,
                "expectancy": expectancy,
                "exposure": exposure,
            },
        },
        "automatic_order": False,
        "automatic_champion_promotion": False,
        "request_text": request_text,
    }


def _config(*, assistant_enabled: bool = False, assistant_provider: str = "deterministic") -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        mode="execute",
        dry_run=False,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_allowed_chat_ids=("100",),
        approval_signing_secret="synthetic-approval-secret",
        assistant_enabled=assistant_enabled,
        assistant_provider=assistant_provider,
        assistant_api_key="ollama-dummy-key",
        assistant_base_url="http://ollama.invalid/v1",
        assistant_model="qwen3:8b",
    )


def _update(update_id: int, message_id: int, text: str, *, chat_id: int = 100) -> dict:
    return {"update_id": update_id, "message": {"message_id": message_id, "chat": {"id": chat_id}, "from": {"id": 200}, "text": text}}


def _production_real_research_update() -> dict:
    return _update(
        91,
        91,
        "가온아 삼성전자 실제 데이터로 아래 전략을 백테스트하고 약점을 분석한 뒤 개선 후보까지 비교해줘.\n\n"
        "20일 고가 돌파\n"
        "종가 > MA20 > MA60\n"
        "거래량 20일 평균 이상\n"
        "손절 -5%\n"
        "10일 저점 이탈 청산",
    )


def _production_autonomous_retest_update() -> dict:
    return _update(
        92,
        92,
        "가온아 삼성전자 실제 데이터로 아래 전략을 충분한 표본이 나올 때까지 자동 재검증해줘.\n\n"
        "20일 고가 돌파\n"
        "종가 > MA20 > MA60\n"
        "거래량 20일 평균 이상\n"
        "손절 -5%\n"
        "10일 저점 이탈 청산\n\n"
        "최초 기간의 거래 표본이 부족하면 18개월, 3년, 5년 순서로 기간을 확장해서 다시 백테스트해줘.\n"
        "각 기간의 거래 수와 결과를 기록하고, 충분한 표본이 확보되거나 최대 기간에 도달할 때까지 진행해줘.\n"
        "마지막에는 원본 전략과 TESTED 개선 후보들을 비교하고 최종 연구 판단을 알려줘.",
    )


def _production_multi_symbol_update() -> dict:
    return _update(93, 93, PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT)


if __name__ == "__main__":
    unittest.main()
