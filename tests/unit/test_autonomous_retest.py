import sqlite3
import unittest

from gaon.research.autonomous_retest import (
    AdaptiveResearchPeriodPlanner,
    AutonomousRetestOrchestrator,
    RetestTriggerEngine,
    StopReason,
    _ReleaseCheckBacktestRunner,
    _ReleaseCheckProvider,
    autonomous_retest_release_check,
    research_retest_history_payload,
    research_retest_status_payload,
)
from gaon.research.operations import BacktestEvidence
from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest, default_tool_registry
from gaon.runtime.migrations import SCHEMA_VERSION, migrate


NOW = "2026-07-26T00:00:00Z"
REQUEST = "20일 고가 돌파 종가 > MA20 > MA60 거래량 20일 평균 이상 손절 -5% 10일 저점 이탈 청산"


class AutonomousRetestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_trigger_requires_retest_for_insufficient_sample(self) -> None:
        evidence = BacktestEvidence("result:low", "strategy:breakout", "2026-01-01", "2026-07-24", "real", False, {"trade_count": 1}, "pass_with_warnings", 1, 0)

        decision = RetestTriggerEngine().evaluate(evidence, min_trades=30, confidence_level="low", next_period="2025-01-01:2026-07-24")

        self.assertTrue(decision.required)
        self.assertEqual(decision.reason, "insufficient_sample")
        self.assertEqual(decision.current_trade_count, 1)
        self.assertEqual(decision.target_min_trades, 30)

    def test_period_planner_expands_deterministically(self) -> None:
        plan = AdaptiveResearchPeriodPlanner().plan(requested_start="2026-01-01", requested_end="2026-07-24")

        self.assertEqual([step.label for step in plan], ["6m", "18m", "3y", "5y"])
        self.assertEqual(plan[-1].end_date, "2026-07-24")
        self.assertLess(plan[-1].start_date, plan[0].start_date)

    def test_user_period_boundary_stops_expansion(self) -> None:
        plan = AdaptiveResearchPeriodPlanner().plan(requested_start="2026-01-01", requested_end="2026-07-24", explicit_user_boundary=True)

        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0].explicit_user_boundary)

    def test_orchestrator_preserves_fingerprints_and_reaches_min_trades(self) -> None:
        run = AutonomousRetestOrchestrator(self.connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(
            REQUEST,
            run_id="unit-retest",
            requested_start="2026-01-01",
            requested_end="2026-07-24",
            min_trades=30,
            generated_at=NOW,
        )

        self.assertEqual(run.stop_reason, StopReason.MIN_TRADES_REACHED)
        self.assertEqual([item.trade_count for item in run.evidence], [1, 5, 17, 31])
        self.assertEqual(run.evidence[-1].backtest.strategy.fingerprint, run.strategy_fingerprint)
        self.assertFalse(run.evidence[-1].backtest.source.value == "fixture")
        self.assertFalse(run.to_json()["automatic_config_apply"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM research_retest_evidence").fetchone()[0], 4)

    def test_candidates_are_tested_not_promoted(self) -> None:
        run = AutonomousRetestOrchestrator(self.connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(REQUEST, run_id="unit-candidates", min_trades=30, generated_at=NOW)

        self.assertEqual(len(run.candidates), 3)
        self.assertTrue(all(candidate.backtest_result is not None for candidate in run.candidates))
        self.assertFalse(run.to_json()["automatic_champion_promotion"])

    def test_status_and_history_safe_tools_are_read_only(self) -> None:
        AutonomousRetestOrchestrator(self.connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(REQUEST, run_id="unit-tool", min_trades=30, generated_at=NOW)
        executor = SafeToolExecutor(default_tool_registry(self.connection))

        status = executor.execute(ToolRequest("research_retest_status", {"limit": 3}, "unit", NOW))
        history = executor.execute(ToolRequest("research_retest_history", {"run_id": "unit-tool"}, "unit", NOW))

        self.assertEqual(status.status, "success")
        self.assertEqual(history.status, "success")
        self.assertFalse(status.output["automatic_order"])
        self.assertGreaterEqual(len(history.output["evidence"]), 4)

    def test_release_check_contract(self) -> None:
        result = autonomous_retest_release_check(self.connection)

        self.assertEqual(result["stop_reason"], "min_trades_reached")
        self.assertEqual(result["evidence"][-1]["trade_count"], 31)
        self.assertGreaterEqual(SCHEMA_VERSION, 35)

    def test_retest_tool_routing(self) -> None:
        self.assertEqual(route_read_only_tool("재검증 상태 알려줘"), "research_retest_status")
        self.assertEqual(route_read_only_tool("재검증 과정과 이력 보여줘"), "research_retest_history")
        self.assertEqual(
            route_read_only_tool(
                "가온아 삼성전자 실제 데이터로 아래 전략을 충분한 표본이 나올 때까지 자동 재검증해줘. "
                "표본이 부족하면 18개월, 3년, 5년 순서로 기간을 확장해서 다시 백테스트해줘."
            ),
            "research_retest",
        )
        self.assertEqual(route_read_only_tool("retest until enough samples and expand period"), "research_retest")

    def test_payload_helpers(self) -> None:
        AutonomousRetestOrchestrator(self.connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(REQUEST, run_id="unit-payload", min_trades=30, generated_at=NOW)

        status = research_retest_status_payload(self.connection)
        history = research_retest_history_payload(self.connection, run_id="unit-payload")

        self.assertFalse(status["empty"])
        self.assertEqual(len(history["evidence"]), 4)
        self.assertIn("quality_findings", status["runs"][0])
        self.assertIn("metrics", history["evidence"][0])

    def test_autonomous_retest_run_id_is_not_filtered_as_artifact(self) -> None:
        run = AutonomousRetestOrchestrator(self.connection, _ReleaseCheckProvider(), _ReleaseCheckBacktestRunner()).run(
            REQUEST,
            run_id="autonomous-retest:production-like",
            min_trades=30,
            generated_at=NOW,
        )

        status = research_retest_status_payload(self.connection)
        history = research_retest_history_payload(self.connection, run_id=run.run_id)

        self.assertFalse(status["empty"])
        self.assertEqual(status["runs"][0]["run_id"], "autonomous-retest:production-like")
        self.assertFalse(history["empty"])


if __name__ == "__main__":
    unittest.main()
