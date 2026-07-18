import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.adapters.backtest import BacktestExecutionContext, BacktestExecutionService, BacktestStatus, FakeBacktestAdapter, build_backtest_request
from gaon.runtime.agents import AgentDispatcher, AgentRequest, AgentStatus, default_agent_registry
from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.executive_planner import DeterministicExecutivePlanner, ExecutiveRequest, RoutingDecision, ToolSelection
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class BacktestAdapterFlowTest(unittest.TestCase):
    def test_executive_planner_to_research_agent_backtest_adapter(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            plan = DeterministicExecutivePlanner().plan(ExecutiveRequest("bt-request", "backtest turtle_v5 on sample_krx", "actor:redacted", NOW))
            result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig(), event_store=SQLiteEventStore(store._connection)).dispatch(plan, AgentRequest("bt-request", "backtest turtle_v5 on sample_krx", "actor:redacted", NOW))

            self.assertEqual(plan.routing_decision, RoutingDecision.RESEARCH)
            self.assertIn(ToolSelection.BACKTEST_ADAPTER, plan.tools)
            self.assertEqual(result.status, AgentStatus.SUCCEEDED)
            self.assertEqual(result.metadata["mode"], "fake_backtest_adapter")
        finally:
            store.close()

    def test_deterministic_backtest_and_failure_do_not_crash(self) -> None:
        request = build_backtest_request("bt-ok", "turtle_v5", "sample_krx", "2024-01-01", "2026-01-01", actor_ref="actor:redacted", created_at=NOW)
        ok = BacktestExecutionService(FakeBacktestAdapter()).run(request, BacktestExecutionContext(30, 64_000, NOW))
        failed = BacktestExecutionService(FakeBacktestAdapter(fail=True)).run(request, BacktestExecutionContext(30, 64_000, NOW))

        self.assertEqual(ok.status, BacktestStatus.COMPLETED)
        self.assertEqual(failed.status, BacktestStatus.FAILED)

    def test_cli_backtest_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["backtest-status", "--db", db]), 0)
            self.assertIn("real v1 engine not required", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["backtest-list-strategies", "--db", db]), 0)
            self.assertIn("turtle_v5", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["backtest-run", "--db", db, "--strategy", "turtle_v5", "--dataset", "sample_krx", "--start", "2024-01-01", "--end", "2026-01-01"]), 0)
            self.assertIn("status=completed", output.getvalue())
            result_id = output.getvalue().split("result_id=", 1)[1].split(" ", 1)[0]

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["backtest-show", "--db", db, result_id]), 0)
            self.assertIn('"status":"completed"', output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["backtest-history", "--db", db]), 0)
            self.assertIn("status=completed", output.getvalue())


if __name__ == "__main__":
    unittest.main()
