import unittest

from gaon.adapters.backtest import BacktestExecutionContext, BacktestExecutionService, FakeBacktestAdapter, SQLiteBacktestRepository, build_backtest_request
from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_revalidation import PaperRevalidationReport, PaperRevalidationStatus, RollbackRecommendation, SQLitePaperRevalidationRepository
from gaon.adapters.strategy_handoff import SQLiteStrategyHandoffRepository, StrategyHandoffService, StrategyHandoffStatus, build_strategy_handoff_request
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class StrategyHandoffFlowTest(unittest.TestCase):
    def test_champion_paper_revalidation_to_approved_handoff_package(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            backtests = SQLiteBacktestRepository(store._connection)
            request = build_backtest_request("integration-bt", "turtle_v5", "kospi_fixture", "2025-01-01", "2025-12-31", actor_ref="actor:redacted", created_at=NOW, parameters={"lookback": 55, "risk_pct": 0.01})
            result = BacktestExecutionService(FakeBacktestAdapter(), repository=backtests).run(request, BacktestExecutionContext(30, 64000, NOW))
            active = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), None).bootstrap(strategy_ref="turtle_v5", fingerprint=result.fingerprint, backtest_id=result.result_id, actor_ref="actor:redacted", activated_at=NOW)
            SQLitePaperRevalidationRepository(store._connection).add_report(
                PaperRevalidationReport("rv-integration", PaperRevalidationStatus.LIVE_ELIGIBLE, "paper_revalidation_policy_v1", "paper-session-integration", active.active_version_id, active.fingerprint, (), (), (), RollbackRecommendation(False, "not recommended"), NOW)
            )

            service = StrategyHandoffService(
                SQLiteStrategyHandoffRepository(store._connection),
                SQLiteChampionRegistryRepository(store._connection),
                SQLitePaperRevalidationRepository(store._connection),
                SQLiteBacktestRepository(store._connection),
                event_store=SQLiteEventStore(store._connection),
                metrics=MetricsCollector(),
            )
            package = service.create(build_strategy_handoff_request("handoff-integration", revalidation_id="rv-integration", actor_ref="actor:redacted", requested_at=NOW))
            approved = service.approve(package.package_id, approver_ref="actor:redacted", decided_at=NOW)

            self.assertEqual(package.status, StrategyHandoffStatus.PENDING_APPROVAL)
            self.assertEqual(approved.status, StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT)
            self.assertEqual(approved.checksum, SQLiteStrategyHandoffRepository(store._connection).latest_approval(package.package_id).package_checksum)
            self.assertEqual(approved.compatibility.required_parameter_keys, ("lookback", "risk_pct"))
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
