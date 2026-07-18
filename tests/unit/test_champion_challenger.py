import os
import sqlite3
import tempfile
import unittest

from gaon.adapters.backtest import build_backtest_request, normalize_v1_backtest_result
from gaon.adapters.champion import (
    ChampionChallengerDecision,
    ChampionChallengerEvaluationEngine,
    ChampionChallengerPolicy,
    ComparisonStatus,
    SQLiteChampionChallengerRepository,
    build_champion_challenger_request,
)
from gaon.adapters.validation import StrategyValidationEngine, ValidationPolicy, ValidationStatus, build_validation_request
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class ChampionChallengerEvaluationTest(unittest.TestCase):
    def result(self, request_id: str, *, strategy="turtle_v5", dataset="sample_krx", total_return=0.20, max_drawdown=0.15, profit_factor=1.4, trade_count=60, start="2024-01-01", end="2026-01-01"):
        request = build_backtest_request(request_id, strategy, dataset, start, end, actor_ref="actor:redacted", created_at=NOW, parameters={"variant": request_id})
        return normalize_v1_backtest_result(
            request,
            {
                "engine_version": "v1-fixture",
                "metrics": {
                    "total_return": total_return,
                    "max_drawdown": max_drawdown,
                    "profit_factor": profit_factor,
                    "trade_count": trade_count,
                    "start_date": start,
                    "end_date": end,
                },
            },
            generated_at=NOW,
        )

    def validation(self, challenger, *, policy=None, validation_id="validation-challenger"):
        request = build_validation_request(validation_id, (challenger,), actor_ref="actor:redacted", requested_at=NOW, policy=policy)
        return StrategyValidationEngine(policy).validate(request, (challenger,), generated_at=NOW)

    def evaluate(self, champion, challenger, validation, *, policy=None, evaluation_id="eval-1"):
        selected_policy = policy or ChampionChallengerPolicy()
        request = build_champion_challenger_request(evaluation_id, champion=champion, challenger=challenger, validation=validation, actor_ref="actor:redacted", requested_at=NOW, policy=selected_policy)
        return ChampionChallengerEvaluationEngine(selected_policy).evaluate(request, champion=champion, challenger=challenger, validation=validation, generated_at=NOW)

    def test_validation_pass_challenger_becomes_promotion_candidate(self) -> None:
        champion = self.result("champion", total_return=0.20, max_drawdown=0.15, profit_factor=1.3)
        challenger = self.result("challenger", total_return=0.27, max_drawdown=0.18, profit_factor=1.5)
        report = self.evaluate(champion, challenger, self.validation(challenger))

        self.assertEqual(report.decision, ChampionChallengerDecision.PROMOTION_CANDIDATE)
        self.assertIn("not promotion", report.rationale)

    def test_validation_fail_keeps_champion_and_review_stays_review(self) -> None:
        champion = self.result("champion", total_return=0.20)
        failed_challenger = self.result("failed-challenger", total_return=0.30, max_drawdown=0.60)
        review_challenger = self.result("review-challenger", total_return=0.30)
        failed_validation = self.validation(failed_challenger)
        review_validation = self.validation(review_challenger, policy=ValidationPolicy(min_sample_days=900))

        self.assertEqual(failed_validation.overall_status, ValidationStatus.FAIL)
        self.assertEqual(self.evaluate(champion, failed_challenger, failed_validation).decision, ChampionChallengerDecision.KEEP_CHAMPION)
        self.assertEqual(review_validation.overall_status, ValidationStatus.REVIEW)
        self.assertEqual(self.evaluate(champion, review_challenger, review_validation).decision, ChampionChallengerDecision.REVIEW)

    def test_same_fingerprint_return_mdd_and_profit_factor_gates(self) -> None:
        champion = self.result("same", total_return=0.20, max_drawdown=0.15, profit_factor=1.5)
        same = champion
        weak_return = self.result("weak-return", total_return=0.23, max_drawdown=0.15, profit_factor=1.6)
        bad_mdd = self.result("bad-mdd", total_return=0.30, max_drawdown=0.25, profit_factor=1.6)
        bad_pf = self.result("bad-pf", total_return=0.30, max_drawdown=0.16, profit_factor=1.0)

        for challenger, metric in ((same, "fingerprint"), (weak_return, "total_return"), (bad_mdd, "max_drawdown"), (bad_pf, "profit_factor")):
            with self.subTest(metric=metric):
                report = self.evaluate(champion, challenger, self.validation(challenger), evaluation_id=f"eval-{metric}")
                failed = {comparison.metric for comparison in report.comparisons if comparison.status == ComparisonStatus.FAIL}
                self.assertEqual(report.decision, ChampionChallengerDecision.KEEP_CHAMPION)
                self.assertIn(metric, failed)

    def test_missing_optional_metric_review_and_score_cannot_override_hard_gate(self) -> None:
        champion = self.result("champion", total_return=0.20, profit_factor=None)
        challenger = self.result("challenger", total_return=0.30, max_drawdown=0.50, profit_factor=None)
        report = self.evaluate(champion, challenger, self.validation(challenger))

        self.assertEqual(report.decision, ChampionChallengerDecision.KEEP_CHAMPION)
        self.assertLessEqual(report.evaluation_score, 69)
        self.assertIn("profit factor comparison was not evaluated because a metric is missing", report.warnings)

    def test_deterministic_persistence_events_metrics_and_migration(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            repository = SQLiteChampionChallengerRepository(store._connection)
            champion = self.result("champion", total_return=0.20)
            challenger = self.result("challenger", total_return=0.30)
            validation = self.validation(challenger)
            request = build_champion_challenger_request("eval-persist", champion=champion, challenger=challenger, validation=validation, actor_ref="actor:redacted", requested_at=NOW)
            engine = ChampionChallengerEvaluationEngine(repository=repository, event_store=SQLiteEventStore(store._connection), metrics=metrics)

            first = engine.evaluate(request, champion=champion, challenger=challenger, validation=validation, generated_at=NOW)
            second = engine.evaluate(request, champion=champion, challenger=challenger, validation=validation, generated_at=NOW)
            events = {event.event_type for event in SQLiteEventStore(store._connection).read_after()}

            self.assertEqual(first.to_json(), second.to_json())
            self.assertEqual(repository.get_report("eval-persist").to_json(), first.to_json())
            self.assertIn("PromotionCandidateIdentified", events)
            self.assertIn("champion_challenger_evaluations_total", metrics.snapshot().to_text())
            self.assertIn("promotion_candidates_total", metrics.snapshot().to_text())
        finally:
            store.close()

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript("CREATE TABLE schema_version (version INTEGER NOT NULL); INSERT INTO schema_version(version) VALUES (13);")
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'champion_challenger_evaluation_requests'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'champion_challenger_evaluation_reports'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
