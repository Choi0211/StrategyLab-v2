import os
import sqlite3
import tempfile
import unittest

from gaon.adapters.champion_registry import ChampionRegistryEntry
from gaon.adapters.paper_forward import PaperTradingPerformanceSummary, PaperTradingSession, PaperTradingSessionStatus
from gaon.adapters.paper_revalidation import PaperRevalidationEngine, PaperRevalidationPolicy, PaperRevalidationStatus, SQLitePaperRevalidationRepository, build_paper_revalidation_request
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class PaperRevalidationTest(unittest.TestCase):
    def active(self, fingerprint="fingerprint1"):
        return ChampionRegistryEntry("default", "champion-version:default:1", "turtle_v5", fingerprint, "backtest1", "validation1", "evaluation1", NOW, 1, None)

    def session(self, status=PaperTradingSessionStatus.COMPLETED, fingerprint="fingerprint1"):
        return PaperTradingSession("paper1", "default", "champion-version:default:1", "turtle_v5", fingerprint, status, "paper_forward_test_policy_v1", NOW, NOW, NOW if status == PaperTradingSessionStatus.COMPLETED else None)

    def summary(self, *, status=PaperTradingSessionStatus.COMPLETED, trades=20, fills=20, rejected=0, failed=0, drawdown=0.10, fingerprint="fingerprint1", errors=()):
        return PaperTradingPerformanceSummary("paper1", status, "champion-version:default:1", "turtle_v5", fingerprint, trades, fills, rejected, failed, 0.0, 0.0, drawdown, 1.0, (), tuple(errors), NOW)

    def revalidate(self, active=None, session=None, summary=None, *, revalidation_id="rv1"):
        session = session or self.session()
        request = build_paper_revalidation_request(revalidation_id, session=session, actor_ref="actor:redacted", requested_at=NOW)
        return PaperRevalidationEngine().revalidate(request, active=active or self.active(), session=session, summary=summary or self.summary(), generated_at=NOW)

    def test_completed_healthy_session_live_eligible(self) -> None:
        self.assertEqual(self.revalidate().status, PaperRevalidationStatus.LIVE_ELIGIBLE)

    def test_incomplete_and_insufficient_trades_hold(self) -> None:
        self.assertEqual(self.revalidate(session=self.session(PaperTradingSessionStatus.ACTIVE), summary=self.summary(status=PaperTradingSessionStatus.ACTIVE)).status, PaperRevalidationStatus.HOLD)
        self.assertEqual(self.revalidate(summary=self.summary(trades=3, fills=3), revalidation_id="rv-low-trades").status, PaperRevalidationStatus.HOLD)

    def test_excessive_drawdown_and_critical_error_kill(self) -> None:
        self.assertEqual(self.revalidate(summary=self.summary(drawdown=0.40), revalidation_id="rv-kill-dd").status, PaperRevalidationStatus.KILL)
        self.assertEqual(self.revalidate(summary=self.summary(failed=1), revalidation_id="rv-kill-error").status, PaperRevalidationStatus.KILL)
        self.assertEqual(self.revalidate(active=self.active("other"), revalidation_id="rv-fingerprint").status, PaperRevalidationStatus.KILL)

    def test_moderate_degradation_recommends_rollback_and_missing_metric_reviews(self) -> None:
        self.assertEqual(self.revalidate(summary=self.summary(drawdown=0.25), revalidation_id="rv-rollback").status, PaperRevalidationStatus.ROLLBACK_RECOMMENDED)
        missing = self.summary()
        missing = PaperTradingPerformanceSummary(missing.session_id, missing.status, missing.champion_version_id, missing.strategy_ref, missing.fingerprint, missing.simulated_orders, missing.fills, missing.rejected_simulated_orders, missing.failed_simulated_orders, None, None, 0.10, None, (), (), NOW)
        self.assertEqual(self.revalidate(summary=missing, revalidation_id="rv-review").status, PaperRevalidationStatus.REVIEW)

    def test_hard_kill_overrides_score_deterministic_events_metrics_persistence(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            repo = SQLitePaperRevalidationRepository(store._connection)
            session = self.session()
            request = build_paper_revalidation_request("rv-persist", session=session, actor_ref="actor:redacted", requested_at=NOW)
            engine = PaperRevalidationEngine(repository=repo, event_store=SQLiteEventStore(store._connection), metrics=metrics)

            first = engine.revalidate(request, active=self.active(), session=session, summary=self.summary(drawdown=0.40), generated_at=NOW)
            second = engine.revalidate(request, active=self.active(), session=session, summary=self.summary(drawdown=0.40), generated_at=NOW)

            self.assertEqual(first.status, PaperRevalidationStatus.KILL)
            self.assertEqual(first.to_json(), second.to_json())
            self.assertEqual(repo.get_report("rv-persist").to_json(), first.to_json())
            self.assertIn("PaperKillGateTriggered", {event.event_type for event in SQLiteEventStore(store._connection).read_after()})
            self.assertIn("gaon_paper_kill_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_migration_v17(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "legacy.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version(version) VALUES (16);")
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'paper_revalidation_requests'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'paper_revalidation_reports'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
