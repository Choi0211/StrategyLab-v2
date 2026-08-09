import sqlite3
import unittest

from gaon.research.autonomous_retest import _ReleaseCheckBacktestRunner, _ReleaseCheckProvider
from gaon.research.multi_symbol import (
    DEFAULT_CURATED_SYMBOLS,
    PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT,
    AutonomousMultiSymbolResearchOrchestrator,
    KRXResearchUniverseResolver,
    aggregate_symbol_evidence,
    compare_candidate_generalization,
    multi_symbol_research_history_payload,
    multi_symbol_research_release_check,
    multi_symbol_research_status_payload,
)
from gaon.runtime.llm_conversation import _default_tool_arguments
from gaon.runtime.intents import Intent, parse_intent
from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest, default_tool_registry
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.routing_debug import telegram_routing_debug_payload


NOW = "2026-07-27T00:00:00Z"
REQUEST = "20일 고가 돌파 종가 > MA20 > MA60 거래량 20일 평균 이상 손절 -5% 10일 저점 이탈 청산"


class MultiSymbolResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_schema_migrates_to_v36(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 36)
        tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("multi_symbol_research_runs", tables)
        self.assertIn("multi_symbol_symbol_evidence", tables)
        self.assertIn("multi_symbol_candidate_evidence", tables)
        self.assertIn("multi_symbol_universe_snapshots", tables)

    def test_explicit_universe_contract(self) -> None:
        universe = KRXResearchUniverseResolver().resolve(("005930", "000660", "005930"), created_at=NOW)
        self.assertEqual(universe.universe_type.value, "explicit")
        self.assertEqual(universe.provenance, "explicit_user_provided")
        self.assertEqual(universe.symbols, ("005930", "000660"))

    def test_orchestrator_persists_per_symbol_and_candidate_evidence(self) -> None:
        run = AutonomousMultiSymbolResearchOrchestrator(self.connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(
            REQUEST,
            run_id="unit:multi-symbol",
            symbols=DEFAULT_CURATED_SYMBOLS,
            generated_at=NOW,
        )

        self.assertEqual(len(run.evidence), 5)
        self.assertTrue(all(item.eligible for item in run.evidence))
        self.assertEqual(run.summary.aggregate_trade_count, 155)
        self.assertEqual(run.summary.sample_confidence, "high")
        self.assertTrue(run.candidate_evidence)
        self.assertFalse(run.to_json()["automatic_champion_promotion"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM multi_symbol_symbol_evidence").fetchone()[0], 5)
        self.assertGreater(self.connection.execute("SELECT COUNT(*) FROM multi_symbol_candidate_evidence").fetchone()[0], 0)

    def test_status_and_history_exclude_release_artifacts(self) -> None:
        AutonomousMultiSymbolResearchOrchestrator(self.connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(
            REQUEST,
            run_id="multi-symbol-research-release-check:artifact",
            symbols=DEFAULT_CURATED_SYMBOLS,
            generated_at=NOW,
        )
        production = AutonomousMultiSymbolResearchOrchestrator(self.connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(
            REQUEST,
            run_id="multi-symbol-research:production-like",
            symbols=DEFAULT_CURATED_SYMBOLS,
            generated_at=NOW,
        )

        status = multi_symbol_research_status_payload(self.connection)
        history = multi_symbol_research_history_payload(self.connection, run_id=production.run_id)

        self.assertEqual(len(status["runs"]), 1)
        self.assertEqual(status["runs"][0]["run_id"], production.run_id)
        self.assertFalse(history["empty"])

    def test_safe_tools_and_routing_are_read_only(self) -> None:
        executor = SafeToolExecutor(default_tool_registry(self.connection))
        result = executor.execute(ToolRequest("multi_symbol_research", {"request_text": REQUEST, "symbols": DEFAULT_CURATED_SYMBOLS}, "unit", NOW))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output["request"]["universe"]["symbols"], list(DEFAULT_CURATED_SYMBOLS))
        self.assertFalse(result.output["automatic_order"])
        self.assertEqual(route_read_only_tool("여러 종목 실제 데이터에서 모두 검증해줘"), "multi_symbol_research")
        self.assertEqual(route_read_only_tool("다중종목 연구 상태 알려줘"), "multi_symbol_research_status")
        self.assertEqual(route_read_only_tool("다중종목 연구 이력 보여줘"), "multi_symbol_research_history")

    def test_production_multi_symbol_phrase_routes_and_extracts_symbols(self) -> None:
        self.assertEqual(route_read_only_tool(PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT), "multi_symbol_research")
        arguments = _default_tool_arguments("multi_symbol_research", PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT)

        self.assertEqual(arguments["symbols"], DEFAULT_CURATED_SYMBOLS)
        self.assertEqual(arguments["start_date"], "2021-07-25")
        self.assertEqual(arguments["end_date"], "2026-07-24")

    def test_production_multi_symbol_routing_debug_prefers_authoritative_tool(self) -> None:
        payload = telegram_routing_debug_payload(PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT)

        self.assertEqual(payload["selected_route"], "tool_read_only_authoritative")
        self.assertEqual(payload["selected_tool"], "multi_symbol_research")
        self.assertEqual(payload["parsed_intent"], "multi_symbol_research")
        self.assertEqual(tuple(payload["detected_symbols"]), DEFAULT_CURATED_SYMBOLS)
        self.assertEqual(payload["detected_dates"], {"start": "2021-07-25", "end": "2026-07-24"})
        self.assertTrue(payload["multi_symbol_evidence"]["execution_intent"])
        self.assertFalse(payload["multi_symbol_evidence"]["history_intent"])
        self.assertFalse(payload["multi_symbol_evidence"]["status_intent"])
        self.assertFalse(payload["blocked"])
        self.assertIsNone(payload["safety_warning"])
        self.assertFalse(payload["provider_allowed"])
        self.assertIsNone(payload["fallback_reason"])

    def test_multi_symbol_recording_request_is_execution_not_history(self) -> None:
        request = "삼성전자와 SK하이닉스를 같은 전략으로 백테스트하고 각 종목 결과를 기록해줘."

        self.assertEqual(route_read_only_tool(request), "multi_symbol_research")
        self.assertEqual(parse_intent(request), Intent.MULTI_SYMBOL_RESEARCH)

    def test_explicit_multi_symbol_history_query_remains_history(self) -> None:
        self.assertEqual(route_read_only_tool("지난 다중종목 연구 기록 보여줘"), "multi_symbol_research_history")

    def test_explicit_multi_symbol_status_query_remains_status(self) -> None:
        self.assertEqual(route_read_only_tool("현재 다중종목 연구 상태 보여줘"), "multi_symbol_research_status")

    def test_single_symbol_retest_and_real_research_priority_are_preserved(self) -> None:
        self.assertEqual(route_read_only_tool("삼성전자 실제 데이터로 자동 재검증해줘"), "research_retest")
        self.assertEqual(route_read_only_tool("삼성전자 실제 데이터로 백테스트하고 약점 분석해줘"), "krx_real_research")

    def test_autonomous_learning_v2_request_has_priority_over_real_research(self) -> None:
        request = (
            "삼성전자 전략을 처음부터 다시 연구해줘. "
            "외부 연구 자료를 찾아보고 실제 시장 데이터로 문제점을 찾고 개선 전략 후보를 검증해줘."
        )

        self.assertEqual(route_read_only_tool(request), "autonomous_learning_research")
        self.assertEqual(route_read_only_tool("계속 연구해줘"), "autonomous_learning_research")

    def test_release_check_contract(self) -> None:
        result = multi_symbol_research_release_check(self.connection)

        self.assertEqual(result["summary"]["total_symbols"], 5)
        self.assertEqual(result["summary"]["sample_confidence"], "high")
        self.assertEqual(result["candidate_generalization"]["decision"], "original_preferred")


if __name__ == "__main__":
    unittest.main()
