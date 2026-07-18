import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.adapters.backtest import SQLiteBacktestRepository, build_backtest_request, normalize_v1_backtest_result
from gaon.adapters.champion import ChampionChallengerEvaluationEngine, SQLiteChampionChallengerRepository, build_champion_challenger_request
from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_forward import SQLitePaperTradingSessionRepository
from gaon.adapters.validation import SQLiteValidationRepository, StrategyValidationEngine, build_validation_request
from gaon.runtime.cli import main as cli_main
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class PaperForwardFlowTest(unittest.TestCase):
    def result(self, request_id: str, *, total_return: float, max_drawdown: float, profit_factor: float):
        request = build_backtest_request(request_id, "turtle_v5", "sample_krx", "2024-01-01", "2026-01-01", actor_ref="actor:redacted", created_at=NOW, parameters={"variant": request_id})
        return normalize_v1_backtest_result(
            request,
            {"engine_version": "v1-fixture", "metrics": {"total_return": total_return, "max_drawdown": max_drawdown, "profit_factor": profit_factor, "trade_count": 60, "start_date": "2024-01-01", "end_date": "2026-01-01"}},
            generated_at=NOW,
        )

    def promote_champion(self, store):
        champion = self.result("champion", total_return=0.20, max_drawdown=0.15, profit_factor=1.3)
        challenger = self.result("challenger", total_return=0.28, max_drawdown=0.18, profit_factor=1.5)
        SQLiteBacktestRepository(store._connection).add_result(champion)
        SQLiteBacktestRepository(store._connection).add_result(challenger)
        validation = StrategyValidationEngine(repository=SQLiteValidationRepository(store._connection)).validate(build_validation_request("validation-candidate", (challenger,), actor_ref="actor:redacted", requested_at=NOW), (challenger,), generated_at=NOW)
        report = ChampionChallengerEvaluationEngine(repository=SQLiteChampionChallengerRepository(store._connection)).evaluate(build_champion_challenger_request("eval-candidate", champion=champion, challenger=challenger, validation=validation, actor_ref="actor:redacted", requested_at=NOW), champion=champion, challenger=challenger, validation=validation, generated_at=NOW)
        service = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection))
        service.bootstrap(strategy_ref="turtle_v5", fingerprint=champion.fingerprint, backtest_id=champion.result_id, actor_ref="actor:redacted", activated_at=NOW)
        service.request_promotion("promotion1", report.evaluation_id, actor_ref="actor:redacted", requested_at=NOW)
        return service.approve("promotion1", actor_ref="actor:redacted", decided_at=NOW), champion

    def test_promoted_champion_paper_session_simulated_order_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                active, _ = self.promote_champion(store)
            finally:
                store.close()

            commands = (
                (["paper-session-create", "--db", db, "--session-id", "paper1", "--champion-version-id", active.active_version_id, "--fingerprint", active.fingerprint], "pending"),
                (["paper-session-start", "--db", db, "paper1"], "active"),
                (["paper-session-simulate-order", "--db", db, "--session-id", "paper1", "--symbol", "005930", "--quantity", "1", "--price", "70000"], "simulated"),
                (["paper-session-summary", "--db", db, "paper1"], "simulated_orders=1"),
                (["paper-session-complete", "--db", db, "paper1"], "completed"),
                (["paper-session-show", "--db", db, "paper1"], '"status":"completed"'),
                (["paper-session-list", "--db", db], "paper1"),
            )
            for argv, expected in commands:
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(cli_main(argv), 0)
                self.assertIn(expected, output.getvalue())

            reopened = RuntimeStateStore(db)
            try:
                self.assertEqual(SQLitePaperTradingSessionRepository(reopened._connection).get_session("paper1").status.value, "completed")
                self.assertEqual(SQLitePaperTradingSessionRepository(reopened._connection).get_summary("paper1").fills, 1)
            finally:
                reopened.close()

    def test_former_champion_and_live_intent_remain_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                active, former = self.promote_champion(store)
            finally:
                store.close()

            with self.assertRaises(ValueError):
                cli_main(["paper-session-create", "--db", db, "--session-id", "stale", "--champion-version-id", "champion-version:default:1", "--fingerprint", former.fingerprint])

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["agent-run", "--agent", "trading", "--request", "live buy 005930 execute", "--db", db]), 0)
            self.assertIn("requires_approval", output.getvalue())
            self.assertIn("live trading is not implemented", output.getvalue())
            self.assertNotIn("live order", output.getvalue().lower())
            self.assertTrue(active.active_version_id)


if __name__ == "__main__":
    unittest.main()
