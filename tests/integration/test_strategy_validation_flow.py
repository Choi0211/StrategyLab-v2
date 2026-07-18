import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.adapters.backtest import BacktestExecutionContext, BacktestExecutionService, FakeBacktestAdapter, SQLiteBacktestRepository, build_backtest_request, normalize_v1_backtest_result
from gaon.adapters.validation import SQLiteValidationRepository, StrategyValidationEngine, ValidationPolicy, ValidationStatus, build_validation_request
from gaon.runtime.agents import AgentDispatcher, AgentRequest, AgentStatus, default_agent_registry
from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.executive_planner import DeterministicExecutivePlanner, ExecutiveRequest, ToolSelection
from gaon.runtime.storage import RuntimeStateStore


NOW = "2026-07-18T00:00:00Z"


class StrategyValidationFlowTest(unittest.TestCase):
    def strong_result(self):
        request = build_backtest_request("bt-strong", "turtle_v5", "sample_krx", "2024-01-01", "2026-01-01", actor_ref="actor:redacted", created_at=NOW)
        return normalize_v1_backtest_result(
            request,
            {"engine_version": "v1-fixture", "metrics": {"total_return": 0.3, "max_drawdown": -0.1, "profit_factor": 1.6, "trade_count": 60, "start_date": "2024-01-01", "end_date": "2026-01-01"}},
            generated_at=NOW,
        )

    def validate(self, result, *, policy=None, validation_id="validation-flow"):
        request = build_validation_request(validation_id, (result,), actor_ref="actor:redacted", requested_at=NOW, policy=policy)
        return StrategyValidationEngine(policy).validate(request, (result,), generated_at=NOW)

    def test_fake_backtest_adapter_to_validation_report(self) -> None:
        request = build_backtest_request("bt-flow", "turtle_v5", "sample_krx", "2024-01-01", "2026-01-01", actor_ref="actor:redacted", created_at=NOW)
        result = BacktestExecutionService(FakeBacktestAdapter()).run(request, BacktestExecutionContext(30, 64_000, NOW))
        report = self.validate(result)

        self.assertEqual(report.fingerprint, result.fingerprint)
        self.assertEqual(report.overall_status, ValidationStatus.FAIL)

    def test_pass_fail_review_and_deterministic_repeated_validation(self) -> None:
        strong = self.strong_result()
        fail = self.validate(strong, policy=ValidationPolicy(max_drawdown=0.01), validation_id="validation-fail")
        review = self.validate(strong, policy=ValidationPolicy(min_sample_days=900), validation_id="validation-review")
        first = self.validate(strong, validation_id="validation-pass")
        second = self.validate(strong, validation_id="validation-pass-repeat")

        self.assertEqual(first.overall_status, ValidationStatus.PASS)
        self.assertEqual(fail.overall_status, ValidationStatus.FAIL)
        self.assertEqual(review.overall_status, ValidationStatus.REVIEW)
        self.assertEqual(first.score, second.score)

    def test_research_agent_backtest_validation_route(self) -> None:
        plan = DeterministicExecutivePlanner().plan(ExecutiveRequest("validate-request", "validate backtest turtle_v5", "actor:redacted", NOW))
        result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig()).dispatch(plan, AgentRequest("validate-request", "validate backtest turtle_v5", "actor:redacted", NOW))

        self.assertIn(ToolSelection.VALIDATION_ENGINE, plan.tools)
        self.assertEqual(result.status, AgentStatus.SUCCEEDED)
        self.assertEqual(result.metadata["mode"], "fake_backtest_validation")
        self.assertIn(result.metadata["validation_status"], {"pass", "fail", "review"})

    def test_persisted_report_reload_and_cli_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            store = RuntimeStateStore(db)
            try:
                backtest_repo = SQLiteBacktestRepository(store._connection)
                validation_repo = SQLiteValidationRepository(store._connection)
                backtest_repo.add_result(self.strong_result())
                report = StrategyValidationEngine(repository=validation_repo, event_store=SQLiteEventStore(store._connection)).validate(build_validation_request("validation-stored", (self.strong_result(),), actor_ref="actor:redacted", requested_at=NOW), (self.strong_result(),), generated_at=NOW)
                self.assertEqual(validation_repo.get_report("validation-stored").to_json(), report.to_json())
            finally:
                store.close()

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["validation-policy-show"]), 0)
            self.assertIn("validation_policy_v1", output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["validation-run", "--db", db, "--backtest-id", self.strong_result().result_id]), 0)
            self.assertIn("validation-run:", output.getvalue())

            validation_id = output.getvalue().split("validation_id=", 1)[1].split(" ", 1)[0]
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["validation-show", "--db", db, validation_id]), 0)
            self.assertIn('"overall_status":"pass"', output.getvalue())

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(["validation-history", "--db", db]), 0)
            self.assertIn("status=pass", output.getvalue())


if __name__ == "__main__":
    unittest.main()
