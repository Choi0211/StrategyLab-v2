import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.adapters.backtest import SQLiteBacktestRepository, build_backtest_request, normalize_v1_backtest_result
from gaon.adapters.champion import ChampionChallengerDecision, ChampionChallengerEvaluationEngine, SQLiteChampionChallengerRepository, build_champion_challenger_request
from gaon.adapters.validation import SQLiteValidationRepository, StrategyValidationEngine, build_validation_request
from gaon.runtime.agents import AgentDispatcher, AgentRequest, AgentStatus, default_agent_registry
from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.executive_planner import DeterministicExecutivePlanner, ExecutiveRequest, ToolSelection
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class ChampionChallengerFlowTest(unittest.TestCase):
    def result(self, request_id: str, *, total_return: float, max_drawdown: float, profit_factor: float):
        request = build_backtest_request(request_id, "turtle_v5", "sample_krx", "2024-01-01", "2026-01-01", actor_ref="actor:redacted", created_at=NOW, parameters={"variant": request_id})
        return normalize_v1_backtest_result(
            request,
            {"engine_version": "v1-fixture", "metrics": {"total_return": total_return, "max_drawdown": max_drawdown, "profit_factor": profit_factor, "trade_count": 60, "start_date": "2024-01-01", "end_date": "2026-01-01"}},
            generated_at=NOW,
        )

    def test_backtest_validation_champion_evaluation_promotion_candidate_flow(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            champion = self.result("champion", total_return=0.20, max_drawdown=0.15, profit_factor=1.3)
            challenger = self.result("challenger", total_return=0.28, max_drawdown=0.18, profit_factor=1.5)
            validation = StrategyValidationEngine(repository=SQLiteValidationRepository(store._connection)).validate(build_validation_request("validation-challenger", (challenger,), actor_ref="actor:redacted", requested_at=NOW), (challenger,), generated_at=NOW)
            request = build_champion_challenger_request("eval-candidate", champion=champion, challenger=challenger, validation=validation, actor_ref="actor:redacted", requested_at=NOW)
            report = ChampionChallengerEvaluationEngine(repository=SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=metrics).evaluate(request, champion=champion, challenger=challenger, validation=validation, generated_at=NOW)

            self.assertEqual(report.decision, ChampionChallengerDecision.PROMOTION_CANDIDATE)
            self.assertEqual(SQLiteChampionChallengerRepository(store._connection).get_report("eval-candidate").to_json(), report.to_json())
            self.assertIn("PromotionCandidateIdentified", {event.event_type for event in SQLiteEventStore(store._connection).read_after()})
            self.assertIn("promotion_candidates_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_keep_champion_flow_and_cli_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                backtests = SQLiteBacktestRepository(store._connection)
                champion = self.result("champion", total_return=0.20, max_drawdown=0.15, profit_factor=1.3)
                challenger = self.result("weak-challenger", total_return=0.22, max_drawdown=0.16, profit_factor=1.4)
                backtests.add_result(champion)
                backtests.add_result(challenger)
                validation = StrategyValidationEngine(repository=SQLiteValidationRepository(store._connection)).validate(build_validation_request("validation-weak", (challenger,), actor_ref="actor:redacted", requested_at=NOW), (challenger,), generated_at=NOW)
                self.assertEqual(validation.overall_status.value, "pass")
            finally:
                store.close()

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["champion-policy-show"]), 0)
            self.assertIn("champion_challenger_policy_v1", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["champion-evaluate", "--db", db, "--champion-backtest-id", champion.result_id, "--challenger-backtest-id", challenger.result_id, "--validation-id", "validation-weak"]), 0)
            self.assertIn("decision=keep_champion", output.getvalue())
            evaluation_id = output.getvalue().split("evaluation_id=", 1)[1].split(" ", 1)[0]

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["champion-evaluation-show", "--db", db, evaluation_id]), 0)
            self.assertIn('"decision":"keep_champion"', output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["champion-evaluation-history", "--db", db]), 0)
            self.assertIn("decision=keep_champion", output.getvalue())

    def test_executive_planner_routes_champion_evaluation_without_promotion(self) -> None:
        plan = DeterministicExecutivePlanner().plan(ExecutiveRequest("champion-route", "champion challenger evaluation", "actor:redacted", NOW))
        result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig()).dispatch(plan, AgentRequest("champion-route", "champion challenger evaluation", "actor:redacted", NOW))

        self.assertIn(ToolSelection.CHAMPION_EVALUATION, plan.tools)
        self.assertEqual(result.status, AgentStatus.SUCCEEDED)
        self.assertEqual(result.metadata["mode"], "champion_evaluation_boundary")
        self.assertEqual(result.metadata["automatic_promotion"], "false")


if __name__ == "__main__":
    unittest.main()
