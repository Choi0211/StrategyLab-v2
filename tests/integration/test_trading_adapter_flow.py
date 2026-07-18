import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.adapters.trading import PaperTradingAdapter, TradingExecutionService, TradingIntent, TradingRiskPolicy, TradingStatus, build_trading_request
from gaon.runtime.agents import AgentDispatcher, AgentRequest, AgentStatus, default_agent_registry
from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.executive_planner import DeterministicExecutivePlanner, ExecutiveRequest, RoutingDecision
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class TradingAdapterFlowTest(unittest.TestCase):
    def test_executive_planner_to_trading_agent_paper_simulation(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            plan = DeterministicExecutivePlanner().plan(ExecutiveRequest("trade-request", "paper simulate buy 005930", "actor:redacted", NOW))
            result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig(), event_store=SQLiteEventStore(store._connection)).dispatch(plan, AgentRequest("trade-request", "paper simulate buy 005930", "actor:redacted", NOW))

            self.assertEqual(plan.routing_decision, RoutingDecision.TRADING)
            self.assertFalse(plan.approval_required)
            self.assertEqual(result.status, AgentStatus.SUCCEEDED)
            self.assertEqual(result.metadata["mode"], "paper_simulation_only")
        finally:
            store.close()

    def test_live_intent_and_approval_required_path_remain_blocked(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            plan = DeterministicExecutivePlanner().plan(ExecutiveRequest("live-request", "live buy 005930 execute", "actor:redacted", NOW))
            result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig(), event_store=SQLiteEventStore(store._connection)).dispatch(plan, AgentRequest("live-request", "live buy 005930 execute", "actor:redacted", NOW))

            self.assertEqual(plan.routing_decision, RoutingDecision.HUMAN_REVIEW)
            self.assertTrue(plan.approval_required)
            self.assertEqual(result.status, AgentStatus.REQUIRES_APPROVAL)
        finally:
            store.close()

    def test_risk_rejection_and_failed_adapter_flow(self) -> None:
        reject = TradingExecutionService(PaperTradingAdapter(), TradingRiskPolicy(max_notional=1.0)).execute(
            build_trading_request("reject", TradingIntent.SIMULATE_BUY, symbol="005930", quantity=1.0, price=70000.0, actor_ref="actor:redacted", created_at=NOW)
        )
        failed = TradingExecutionService(PaperTradingAdapter(fail_simulation=True), TradingRiskPolicy()).execute(
            build_trading_request("failure", TradingIntent.SIMULATE_BUY, symbol="005930", quantity=1.0, price=70000.0, actor_ref="actor:redacted", created_at=NOW)
        )

        self.assertEqual(reject.status, TradingStatus.REJECTED)
        self.assertEqual(failed.status, TradingStatus.FAILED)

    def test_cli_trading_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["trading-status", "--db", db]), 0)
            self.assertIn("live trading disabled", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["trading-account", "--db", db]), 0)
            self.assertIn("paper-account", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["trading-simulate-buy", "--db", db, "--symbol", "005930", "--quantity", "1", "--price", "70000"]), 0)
            self.assertIn("status=simulated", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["trading-history", "--db", db]), 0)
            self.assertIn("status=simulated", output.getvalue())


if __name__ == "__main__":
    unittest.main()
