import os
import sqlite3
import tempfile
import unittest

from gaon.adapters.backtest import build_backtest_request, normalize_v1_backtest_result
from gaon.adapters.champion import ChampionChallengerEvaluationEngine, ChampionChallengerDecision, SQLiteChampionChallengerRepository, build_champion_challenger_request
from gaon.adapters.champion_registry import ChampionRegistryService, ChampionRollbackRequest, PromotionStatus, SQLiteChampionRegistryRepository
from gaon.adapters.validation import StrategyValidationEngine, ValidationPolicy, build_validation_request
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class ChampionRegistryTest(unittest.TestCase):
    def result(self, request_id: str, *, total_return=0.20, max_drawdown=0.15, profit_factor=1.4):
        request = build_backtest_request(request_id, "turtle_v5", "sample_krx", "2024-01-01", "2026-01-01", actor_ref="actor:redacted", created_at=NOW, parameters={"variant": request_id})
        return normalize_v1_backtest_result(
            request,
            {"engine_version": "v1-fixture", "metrics": {"total_return": total_return, "max_drawdown": max_drawdown, "profit_factor": profit_factor, "trade_count": 60, "start_date": "2024-01-01", "end_date": "2026-01-01"}},
            generated_at=NOW,
        )

    def service(self, store, metrics=None):
        return ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=metrics)

    def evaluation(self, store, *, evaluation_id="eval-candidate", champion=None, challenger=None, policy=None):
        champion = champion or self.result("champion", total_return=0.20, max_drawdown=0.15, profit_factor=1.3)
        challenger = challenger or self.result("challenger", total_return=0.28, max_drawdown=0.18, profit_factor=1.5)
        validation = StrategyValidationEngine(policy).validate(build_validation_request(f"validation:{evaluation_id}", (challenger,), actor_ref="actor:redacted", requested_at=NOW, policy=policy), (challenger,), generated_at=NOW)
        request = build_champion_challenger_request(evaluation_id, champion=champion, challenger=challenger, validation=validation, actor_ref="actor:redacted", requested_at=NOW)
        return ChampionChallengerEvaluationEngine(repository=SQLiteChampionChallengerRepository(store._connection)).evaluate(request, champion=champion, challenger=challenger, validation=validation, generated_at=NOW)

    def test_bootstrap_first_champion_and_duplicate_rejected(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            service = self.service(store)
            entry = service.bootstrap(strategy_ref="turtle_v5", fingerprint="fingerprint1", backtest_id="backtest1", actor_ref="actor:redacted", activated_at=NOW)

            self.assertEqual(entry.revision, 1)
            self.assertEqual(SQLiteChampionRegistryRepository(store._connection).get_active().fingerprint, "fingerprint1")
            with self.assertRaises(ValueError):
                service.bootstrap(strategy_ref="turtle_v5", fingerprint="fingerprint2", backtest_id="backtest2", actor_ref="actor:redacted", activated_at=NOW)
        finally:
            store.close()

    def test_valid_promotion_request_and_approval_changes_active_champion(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            service = self.service(store, metrics)
            service.bootstrap(strategy_ref="turtle_v5", fingerprint="initialfingerprint", backtest_id="backtest0", actor_ref="actor:redacted", activated_at=NOW)
            report = self.evaluation(store)

            request = service.request_promotion("promotion1", report.evaluation_id, actor_ref="actor:redacted", requested_at=NOW)
            self.assertEqual(request.status, PromotionStatus.PENDING_APPROVAL)
            self.assertEqual(SQLiteChampionRegistryRepository(store._connection).get_active().fingerprint, "initialfingerprint")

            active = service.approve("promotion1", actor_ref="actor:redacted", decided_at=NOW)
            again = service.approve("promotion1", actor_ref="actor:redacted", decided_at=NOW)
            self.assertEqual(active.to_json(), again.to_json())
            self.assertEqual(active.fingerprint, report.challenger_fingerprint)
            self.assertEqual(len(SQLiteChampionRegistryRepository(store._connection).list_history()), 2)
            events = {event.event_type for event in SQLiteEventStore(store._connection).read_after()}
            self.assertIn("ChampionPromotionApproved", events)
            self.assertIn("ChampionActivated", events)
            self.assertIn("gaon_champion_activations_total", metrics.snapshot().to_text())
        finally:
            store.close()

    def test_invalid_and_non_candidate_evaluations_are_rejected(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            service = self.service(store)
            service.bootstrap(strategy_ref="turtle_v5", fingerprint="initialfingerprint", backtest_id="backtest0", actor_ref="actor:redacted", activated_at=NOW)
            keep = self.evaluation(store, evaluation_id="eval-keep", challenger=self.result("weak", total_return=0.21, max_drawdown=0.15, profit_factor=1.5))
            review = self.evaluation(store, evaluation_id="eval-review", policy=ValidationPolicy(min_sample_days=900))

            self.assertEqual(keep.decision, ChampionChallengerDecision.KEEP_CHAMPION)
            self.assertEqual(review.decision, ChampionChallengerDecision.REVIEW)
            with self.assertRaises(ValueError):
                service.request_promotion("promotion-keep", keep.evaluation_id, actor_ref="actor:redacted", requested_at=NOW)
            with self.assertRaises(ValueError):
                service.request_promotion("promotion-review", review.evaluation_id, actor_ref="actor:redacted", requested_at=NOW)
            with self.assertRaises(KeyError):
                service.request_promotion("promotion-missing", "missing", actor_ref="actor:redacted", requested_at=NOW)
        finally:
            store.close()

    def test_reject_keeps_champion_and_duplicate_request_is_idempotent(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            service = self.service(store)
            service.bootstrap(strategy_ref="turtle_v5", fingerprint="initialfingerprint", backtest_id="backtest0", actor_ref="actor:redacted", activated_at=NOW)
            report = self.evaluation(store)
            request = service.request_promotion("promotion1", report.evaluation_id, actor_ref="actor:redacted", requested_at=NOW)
            same = service.request_promotion("promotion1", report.evaluation_id, actor_ref="actor:redacted", requested_at=NOW)

            self.assertEqual(request.to_json(), same.to_json())
            rejected = service.reject("promotion1", actor_ref="actor:redacted", decided_at=NOW)
            self.assertEqual(rejected.status, PromotionStatus.REJECTED)
            self.assertEqual(SQLiteChampionRegistryRepository(store._connection).get_active().fingerprint, "initialfingerprint")
            with self.assertRaises(ValueError):
                service.approve("promotion1", actor_ref="actor:redacted", decided_at=NOW)
        finally:
            store.close()

    def test_rollback_restores_previous_champion_and_without_previous_rejected(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            service = self.service(store)
            service.bootstrap(strategy_ref="turtle_v5", fingerprint="initialfingerprint", backtest_id="backtest0", actor_ref="actor:redacted", activated_at=NOW)
            with self.assertRaises(ValueError):
                service.rollback(ChampionRollbackRequest("rollback0", "default", "actor:redacted", NOW))
            report = self.evaluation(store)
            service.request_promotion("promotion1", report.evaluation_id, actor_ref="actor:redacted", requested_at=NOW)
            service.approve("promotion1", actor_ref="actor:redacted", decided_at=NOW)

            result = service.rollback(ChampionRollbackRequest("rollback1", "default", "actor:redacted", NOW))
            active = SQLiteChampionRegistryRepository(store._connection).get_active()
            self.assertEqual(result.status, PromotionStatus.ROLLED_BACK)
            self.assertEqual(active.fingerprint, "initialfingerprint")
            self.assertEqual(len(SQLiteChampionRegistryRepository(store._connection).list_history()), 3)
        finally:
            store.close()

    def test_persistence_round_trip_and_migration_v15(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                self.service(store).bootstrap(strategy_ref="turtle_v5", fingerprint="initialfingerprint", backtest_id="backtest0", actor_ref="actor:redacted", activated_at=NOW)
            finally:
                store.close()
            reopened = RuntimeStateStore(db)
            try:
                self.assertEqual(SQLiteChampionRegistryRepository(reopened._connection).get_active().fingerprint, "initialfingerprint")
            finally:
                reopened.close()

            legacy = os.path.join(tmp, "legacy.sqlite")
            connection = sqlite3.connect(legacy)
            connection.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version(version) VALUES (14);")
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'champion_registry'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
