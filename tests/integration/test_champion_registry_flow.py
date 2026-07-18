import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.adapters.backtest import SQLiteBacktestRepository, build_backtest_request, normalize_v1_backtest_result
from gaon.adapters.champion import ChampionChallengerEvaluationEngine, SQLiteChampionChallengerRepository, build_champion_challenger_request
from gaon.adapters.champion_registry import SQLiteChampionRegistryRepository
from gaon.adapters.validation import SQLiteValidationRepository, StrategyValidationEngine, build_validation_request
from gaon.runtime.cli import main as cli_main
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class ChampionRegistryFlowTest(unittest.TestCase):
    def result(self, request_id: str, *, total_return: float, max_drawdown: float, profit_factor: float):
        request = build_backtest_request(request_id, "turtle_v5", "sample_krx", "2024-01-01", "2026-01-01", actor_ref="actor:redacted", created_at=NOW, parameters={"variant": request_id})
        return normalize_v1_backtest_result(
            request,
            {"engine_version": "v1-fixture", "metrics": {"total_return": total_return, "max_drawdown": max_drawdown, "profit_factor": profit_factor, "trade_count": 60, "start_date": "2024-01-01", "end_date": "2026-01-01"}},
            generated_at=NOW,
        )

    def build_candidate(self, store, suffix="candidate"):
        champion = self.result(f"champion-{suffix}", total_return=0.20, max_drawdown=0.15, profit_factor=1.3)
        challenger = self.result(f"challenger-{suffix}", total_return=0.28, max_drawdown=0.18, profit_factor=1.5)
        SQLiteBacktestRepository(store._connection).add_result(champion)
        SQLiteBacktestRepository(store._connection).add_result(challenger)
        validation = StrategyValidationEngine(repository=SQLiteValidationRepository(store._connection)).validate(build_validation_request(f"validation-{suffix}", (challenger,), actor_ref="actor:redacted", requested_at=NOW), (challenger,), generated_at=NOW)
        request = build_champion_challenger_request(f"eval-{suffix}", champion=champion, challenger=challenger, validation=validation, actor_ref="actor:redacted", requested_at=NOW)
        report = ChampionChallengerEvaluationEngine(repository=SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection)).evaluate(request, champion=champion, challenger=challenger, validation=validation, generated_at=NOW)
        return champion, challenger, report

    def test_candidate_approval_updates_registry_and_restart_preserves_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                champion, challenger, report = self.build_candidate(store)
            finally:
                store.close()

            for argv, expected in (
                (["champion-bootstrap", "--db", db, "--strategy", "turtle_v5", "--fingerprint", champion.fingerprint, "--backtest-id", champion.result_id], "champion-bootstrap:"),
                (["champion-promotion-request", "--db", db, "--evaluation-id", report.evaluation_id, "--promotion-id", "promotion1"], "pending_approval"),
                (["champion-promotion-approve", "--db", db, "promotion1"], challenger.fingerprint),
                (["champion-registry-show", "--db", db], challenger.fingerprint),
                (["champion-history", "--db", db], "revision=2"),
            ):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(cli_main(argv), 0)
                self.assertIn(expected, output.getvalue())

            reopened = RuntimeStateStore(db)
            try:
                self.assertEqual(SQLiteChampionRegistryRepository(reopened._connection).get_active().fingerprint, challenger.fingerprint)
            finally:
                reopened.close()

    def test_rejected_promotion_and_rollback_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                champion, challenger, report = self.build_candidate(store)
            finally:
                store.close()

            self.assertEqual(cli_main(["champion-bootstrap", "--db", db, "--strategy", "turtle_v5", "--fingerprint", champion.fingerprint, "--backtest-id", champion.result_id]), 0)
            self.assertEqual(cli_main(["champion-promotion-request", "--db", db, "--evaluation-id", report.evaluation_id, "--promotion-id", "promotion-reject"]), 0)
            self.assertEqual(cli_main(["champion-promotion-reject", "--db", db, "promotion-reject"]), 0)
            store = RuntimeStateStore(db)
            try:
                self.assertEqual(SQLiteChampionRegistryRepository(store._connection).get_active().fingerprint, champion.fingerprint)
            finally:
                store.close()

            self.assertEqual(cli_main(["champion-promotion-request", "--db", db, "--evaluation-id", report.evaluation_id, "--promotion-id", "promotion-reject"]), 0)
            with self.assertRaises(ValueError):
                cli_main(["champion-promotion-approve", "--db", db, "promotion-reject"])

            # A second evaluation drives approval, then rollback restores the first champion.
            store = RuntimeStateStore(db)
            try:
                _, _, second = self.build_candidate(store, "second")
            finally:
                store.close()
            self.assertEqual(cli_main(["champion-promotion-request", "--db", db, "--evaluation-id", second.evaluation_id, "--promotion-id", "promotion2"]), 0)
            self.assertEqual(cli_main(["champion-promotion-approve", "--db", db, "promotion2"]), 0)
            self.assertEqual(cli_main(["champion-rollback", "--db", db, "--rollback-id", "rollback1"]), 0)
            store = RuntimeStateStore(db)
            try:
                self.assertEqual(SQLiteChampionRegistryRepository(store._connection).get_active().fingerprint, champion.fingerprint)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
