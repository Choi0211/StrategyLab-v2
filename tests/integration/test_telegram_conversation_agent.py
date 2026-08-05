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
) -> SafeToolExecutor:
    registry = ToolRegistry()

    def handle(args):
        symbol = str(args.get("symbol", "005930"))
        if fail_symbol == symbol:
            raise RealMarketDataUnavailable(f"real_data_unavailable: synthetic failure for {symbol}")
        return _sprint152_payload(symbol, fixture_backed=fixture_backed, zero_trade_symbols=zero_trade_symbols)

    registry.register(
        ToolDefinition(
            "krx_real_research",
            "Run the read-only KRX real-research pipeline with explicit source provenance.",
            ToolRiskLevel.READ_ONLY,
            required_args=("request_text",),
            allowed_args=("symbol",),
        ),
        handle,
    )
    return SafeToolExecutor(registry, store.tool_audit)


def _sprint152_payload(symbol: str, *, fixture_backed: bool = True, zero_trade_symbols: tuple[str, ...] = ()) -> dict[str, object]:
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
                "start_date": "2026-01-02",
                "end_date": "2026-07-10",
                "fixture_backed": fixture_backed,
            },
        },
        "quality": {"status": "pass", "findings": []},
        "strategy": {"fingerprint": f"strategy:{symbol}"},
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
