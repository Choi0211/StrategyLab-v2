import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_forward import PaperTradingForwardTestService, SQLitePaperTradingSessionRepository
from gaon.adapters.paper_revalidation import PaperRevalidationStatus, SQLitePaperRevalidationRepository
from gaon.runtime.cli import main as cli_main
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class PaperRevalidationFlowTest(unittest.TestCase):
    def bootstrap_session(self, db: str, *, session_id="paper1", orders=20, complete=True):
        store = RuntimeStateStore(db)
        try:
            ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), None).bootstrap(strategy_ref="turtle_v5", fingerprint="fingerprint1", backtest_id="backtest1", actor_ref="actor:redacted", activated_at=NOW)
            service = PaperTradingForwardTestService(SQLitePaperTradingSessionRepository(store._connection), SQLiteChampionRegistryRepository(store._connection), event_store=SQLiteEventStore(store._connection))
            service.create_session(session_id, actor_ref="actor:redacted", created_at=NOW)
            service.start(session_id, actor_ref="actor:redacted", at=NOW)
            for index in range(orders):
                at = f"2026-07-18T00:00:{index:02d}Z"
                service.simulate_order(session_id, symbol="005930", quantity=1, price=70000 + index, side="buy", actor_ref="actor:redacted", at=at)
            if complete:
                service.complete(session_id, actor_ref="actor:redacted", at=NOW)
            else:
                service.summary(session_id, generated_at=NOW)
            if complete and orders >= 20:
                from gaon.adapters.paper_forward import PaperTradingPerformanceSummary

                sessions = SQLitePaperTradingSessionRepository(store._connection)
                summary = sessions.get_summary(session_id)
                sessions.put_summary(PaperTradingPerformanceSummary(summary.session_id, summary.status, summary.champion_version_id, summary.strategy_ref, summary.fingerprint, summary.simulated_orders, summary.fills, summary.rejected_simulated_orders, summary.failed_simulated_orders, 0.0, 0.0, 0.10, 1.0, (), (), NOW))
        finally:
            store.close()

    def test_revalidation_live_eligible_cli_flow_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            self.bootstrap_session(db)

            for argv, expected in (
                (["paper-revalidation-policy-show"], "paper_revalidation_policy_v1"),
                (["paper-revalidate", "--db", db, "--session-id", "paper1", "--revalidation-id", "rv1"], "live_eligible"),
                (["paper-revalidation-show", "--db", db, "rv1"], '"status":"live_eligible"'),
                (["paper-revalidation-history", "--db", db], "rv1"),
            ):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(cli_main(argv), 0)
                self.assertIn(expected, output.getvalue())

            reopened = RuntimeStateStore(db)
            try:
                self.assertEqual(SQLitePaperRevalidationRepository(reopened._connection).get_report("rv1").status, PaperRevalidationStatus.LIVE_ELIGIBLE)
            finally:
                reopened.close()

    def test_kill_and_rollback_recommended_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            self.bootstrap_session(db, session_id="hold-session", orders=3)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["paper-revalidate", "--db", db, "--session-id", "hold-session", "--revalidation-id", "rv-hold"]), 0)
            self.assertIn("hold", output.getvalue())

            store = RuntimeStateStore(db)
            try:
                sessions = SQLitePaperTradingSessionRepository(store._connection)
                summary = sessions.get_summary("hold-session")
                from gaon.adapters.paper_forward import PaperTradingPerformanceSummary

                sessions.put_summary(PaperTradingPerformanceSummary(summary.session_id, summary.status, summary.champion_version_id, summary.strategy_ref, summary.fingerprint, 20, 20, 0, 0, 0.0, 0.0, 0.40, 1.0, (), (), NOW))
            finally:
                store.close()
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["paper-revalidate", "--db", db, "--session-id", "hold-session", "--revalidation-id", "rv-kill"]), 0)
            self.assertIn("kill", output.getvalue())

            store = RuntimeStateStore(db)
            try:
                sessions = SQLitePaperTradingSessionRepository(store._connection)
                summary = sessions.get_summary("hold-session")
                from gaon.adapters.paper_forward import PaperTradingPerformanceSummary

                sessions.put_summary(PaperTradingPerformanceSummary(summary.session_id, summary.status, summary.champion_version_id, summary.strategy_ref, summary.fingerprint, 20, 20, 0, 0, 0.0, 0.0, 0.25, 1.0, (), (), NOW))
            finally:
                store.close()
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["paper-revalidate", "--db", db, "--session-id", "hold-session", "--revalidation-id", "rv-rollback"]), 0)
            self.assertIn("rollback_recommended", output.getvalue())


if __name__ == "__main__":
    unittest.main()
