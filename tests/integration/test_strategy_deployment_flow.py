import unittest

from gaon.adapters.backtest import BacktestExecutionContext, BacktestExecutionService, FakeBacktestAdapter, SQLiteBacktestRepository, build_backtest_request
from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_revalidation import PaperRevalidationReport, PaperRevalidationStatus, RollbackRecommendation, SQLitePaperRevalidationRepository
from gaon.adapters.strategy_deployment import FakeStrategyDeploymentAdapter, SQLiteStrategyDeploymentRepository, StrategyDeploymentService, StrategyDeploymentStatus, build_strategy_deployment_request
from gaon.adapters.strategy_handoff import SQLiteStrategyHandoffRepository, StrategyHandoffService, build_strategy_handoff_request
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class StrategyDeploymentFlowTest(unittest.TestCase):
    def approved_package(self, store):
        backtests = SQLiteBacktestRepository(store._connection)
        request = build_backtest_request("deploy-flow-bt", "turtle_v5", "kospi_fixture", "2025-01-01", "2025-12-31", actor_ref="actor:redacted", created_at=NOW, parameters={"lookback": 55})
        result = BacktestExecutionService(FakeBacktestAdapter(), repository=backtests).run(request, BacktestExecutionContext(30, 64000, NOW))
        active = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), None).bootstrap(strategy_ref="turtle_v5", fingerprint=result.fingerprint, backtest_id=result.result_id, actor_ref="actor:redacted", activated_at=NOW)
        SQLitePaperRevalidationRepository(store._connection).add_report(PaperRevalidationReport("rv-deploy-flow", PaperRevalidationStatus.LIVE_ELIGIBLE, "paper_revalidation_policy_v1", "paper-session-flow", active.active_version_id, active.fingerprint, (), (), (), RollbackRecommendation(False, "not recommended"), NOW))
        service = StrategyHandoffService(SQLiteStrategyHandoffRepository(store._connection), SQLiteChampionRegistryRepository(store._connection), SQLitePaperRevalidationRepository(store._connection), SQLiteBacktestRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
        package = service.create(build_strategy_handoff_request("handoff-deploy-flow", revalidation_id="rv-deploy-flow", actor_ref="actor:redacted", requested_at=NOW))
        return service.approve(package.package_id, approver_ref="actor:redacted", decided_at=NOW)

    def service(self, store, adapter):
        return StrategyDeploymentService(SQLiteStrategyDeploymentRepository(store._connection), SQLiteStrategyHandoffRepository(store._connection), SQLiteChampionRegistryRepository(store._connection), adapter, event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())

    def test_approved_handoff_package_deploys_successfully(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            package = self.approved_package(store)
            service = self.service(store, FakeStrategyDeploymentAdapter())
            plan = service.plan(build_strategy_deployment_request("deploy-flow", package_id=package.package_id, actor_ref="actor:redacted", requested_at=NOW))
            run = service.run(plan.plan_id, actor_ref="actor:redacted", at=NOW)
            self.assertEqual(plan.status, StrategyDeploymentStatus.PREFLIGHT_PASSED)
            self.assertEqual(run.status, StrategyDeploymentStatus.SUCCEEDED)
        finally:
            store.close()

    def test_apply_then_verify_failure_rolls_back(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            package = self.approved_package(store)
            service = self.service(store, FakeStrategyDeploymentAdapter(fail_verify=True))
            plan = service.plan(build_strategy_deployment_request("deploy-flow-rollback", package_id=package.package_id, actor_ref="actor:redacted", requested_at=NOW))
            run = service.run(plan.plan_id, actor_ref="actor:redacted", at=NOW)
            self.assertEqual(run.status, StrategyDeploymentStatus.ROLLED_BACK)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
