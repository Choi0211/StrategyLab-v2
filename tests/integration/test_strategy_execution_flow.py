import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_forward import PaperTradingForwardTestService, SQLitePaperTradingSessionRepository, PaperTradingPerformanceSummary
from gaon.adapters.paper_revalidation import PaperRevalidationEngine, SQLitePaperRevalidationRepository, build_paper_revalidation_request
from gaon.adapters.strategy_execution import SQLiteStrategyExecutionRepository
from gaon.runtime.cli import main as cli_main
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class StrategyExecutionFlowTest(unittest.TestCase):
    def prepare_live_eligible(self, db: str):
        store = RuntimeStateStore(db)
        try:
            active = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), None).bootstrap(strategy_ref="turtle_v5", fingerprint="fingerprint1", backtest_id="backtest1", actor_ref="actor:redacted", activated_at=NOW)
            paper = PaperTradingForwardTestService(SQLitePaperTradingSessionRepository(store._connection), SQLiteChampionRegistryRepository(store._connection))
            paper.create_session("paper1", actor_ref="actor:redacted", created_at=NOW)
            paper.start("paper1", actor_ref="actor:redacted", at=NOW)
            for index in range(20):
                paper.simulate_order("paper1", symbol="005930", quantity=1, price=70000 + index, side="buy", actor_ref="actor:redacted", at=f"2026-07-18T00:00:{index:02d}Z")
            paper.complete("paper1", actor_ref="actor:redacted", at=NOW)
            sessions = SQLitePaperTradingSessionRepository(store._connection)
            summary = sessions.get_summary("paper1")
            sessions.put_summary(PaperTradingPerformanceSummary(summary.session_id, summary.status, summary.champion_version_id, summary.strategy_ref, summary.fingerprint, summary.simulated_orders, summary.fills, summary.rejected_simulated_orders, summary.failed_simulated_orders, 0.0, 0.0, 0.10, 1.0, (), (), NOW))
            session = sessions.get_session("paper1")
            request = build_paper_revalidation_request("rv1", session=session, actor_ref="actor:redacted", requested_at=NOW)
            PaperRevalidationEngine(repository=SQLitePaperRevalidationRepository(store._connection)).revalidate(request, active=active, session=session, summary=sessions.get_summary("paper1"), generated_at=NOW)
            return active
        finally:
            store.close()

    def test_live_eligible_allows_paper_execution_and_blocks_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            self.prepare_live_eligible(db)

            for argv, expected in (
                (["execution-policy-show"], "strategy_execution_policy_v1"),
                (["execution-plan", "--db", db, "--mode", "paper", "--plan-id", "paper-plan"], "status=ready"),
                (["execution-run", "--db", db, "--plan-id", "execution-plan:paper-plan"], "status=completed"),
                (["execution-plan", "--db", db, "--mode", "live", "--plan-id", "live-plan", "--revalidation-id", "rv1"], "blocked"),
                (["execution-status", "--db", db], "runs=1"),
                (["execution-history", "--db", db], "completed"),
            ):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(cli_main(argv), 0)
                self.assertIn(expected, output.getvalue().lower())

            reopened = RuntimeStateStore(db)
            try:
                self.assertEqual(len(SQLiteStrategyExecutionRepository(reopened._connection).list_runs()), 1)
            finally:
                reopened.close()

    def test_hold_revalidation_blocks_live_and_stale_plan_blocks_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            self.prepare_live_eligible(db)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["execution-plan", "--db", db, "--mode", "paper", "--plan-id", "stale-paper"]), 0)
            store = RuntimeStateStore(db)
            try:
                current = SQLiteChampionRegistryRepository(store._connection).get_active()
                SQLiteChampionRegistryRepository(store._connection).put_active(type(current)("default", "champion-version:default:99", current.strategy_ref, "fingerprint2", current.source_backtest_id, current.source_validation_id, current.source_evaluation_id, NOW, 99, current.active_version_id))
            finally:
                store.close()
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["execution-run", "--db", db, "--plan-id", "execution-plan:stale-paper"]), 0)
            self.assertIn("stale champion", output.getvalue())


if __name__ == "__main__":
    unittest.main()
