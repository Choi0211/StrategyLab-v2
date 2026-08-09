from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from gaon.knowledge.autonomous_learning_e2e import autonomous_learning_e2e_release_check
from gaon.knowledge.execution import DEFAULT_ALLOWED_API_HOSTS, NetworkExecutionPolicy
from gaon.knowledge.telegram_autonomous_learning import (
    _ReleaseMetadataTransport,
    _run_production_external_research,
    production_autonomous_learning_execution_release_check,
    production_external_research_network_release_check,
    production_autonomous_learning_payload_from_baseline,
    telegram_autonomous_learning_payload,
)
from gaon.research.krx_real_pipeline import MarketDataAvailability
from gaon.runtime.storage import RuntimeStateStore
from tests.fixtures.knowledge_pipeline import build_experiment, build_real_backtest


class AutonomousLearningE2EReleaseCheckTests(unittest.TestCase):
    def test_release_check_reaches_human_approval_required(self) -> None:
        payload = autonomous_learning_e2e_release_check()

        self.assertEqual("proposed", payload["hypothesis_status"])
        self.assertEqual("accepted_for_review", payload["validation_status"])
        self.assertEqual("ranked", payload["ranking_status"])
        self.assertEqual("requires_human_approval", payload["promotion_status"])
        self.assertEqual("awaiting_human_approval", payload["human_gate_status"])
        self.assertEqual("pass", payload["safety"])

    def test_telegram_wrapper_blocks_fixture_release_evidence_in_production(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            payload = telegram_autonomous_learning_payload(
                store._connection,
                "삼성전자 전략을 처음부터 다시 연구해줘",
                symbol="005930",
            )

            self.assertEqual("autonomous_learning_research", payload["tool"])
            self.assertEqual("005930", payload["symbol"])
            self.assertEqual("autonomous_learning_v2", payload["selected_orchestration"])
            self.assertEqual("blocked_fixture", payload["promotion_status"])
            self.assertEqual("not_requested", payload["human_gate_status"])
            self.assertFalse(payload["approval_required"])
            self.assertTrue(payload["fixture_promotion_blocked"])
            self.assertFalse(payload["production_uses_release_fixture"])
            self.assertFalse(payload["strategy_mutated"])
            self.assertFalse(payload["order_executed"])
            self.assertFalse(payload["broker_order_called"])
            self.assertFalse(payload["kis_order_called"])
            self.assertIn("baseline", payload)
        finally:
            store.close()

    def test_production_wrapper_does_not_call_release_check_or_fixture_helpers(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            with patch(
                "gaon.knowledge.autonomous_learning_e2e.autonomous_learning_e2e_release_check",
                side_effect=AssertionError("release fixture called"),
            ):
                with patch(
                    "gaon.knowledge.experiment_execution._fixture_experiment_and_backtest",
                    side_effect=AssertionError("fixture backtest helper called"),
                ):
                    payload = telegram_autonomous_learning_payload(store._connection, "삼성전자 전략 연구해줘", symbol="005930")
            self.assertFalse(payload["production_uses_release_fixture"])
            self.assertNotEqual("requires_human_approval", payload["promotion_status"])
        finally:
            store.close()

    def test_real_baseline_with_fixture_candidate_evidence_is_blocked(self) -> None:
        experiment = build_experiment()
        backtest = build_real_backtest(experiment)
        payload = _baseline_payload(experiment, backtest, baseline_fixture=False)

        result = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략 연구해줘",
            symbol="005930",
            mode="research",
            baseline=payload,
            external_research=_external_ready(),
        )

        self.assertEqual("blocked_fixture", result["promotion_status"])
        self.assertFalse(result["approval_required"])
        self.assertTrue(result["fixture_promotion_blocked"])

    def test_real_candidate_backtest_fingerprint_must_match_experiment_candidate(self) -> None:
        experiment = build_experiment()
        backtest = build_real_backtest(experiment, source=MarketDataAvailability.REAL)
        payload = _baseline_payload(experiment, backtest, baseline_fixture=False)
        payload["candidates"][0]["strategy"]["fingerprint"] = "different"

        result = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략 연구해줘",
            symbol="005930",
            mode="research",
            baseline=payload,
            external_research=_external_ready(),
        )

        self.assertFalse(result["candidate_strategy_fingerprint_matched"])
        self.assertNotEqual("requires_human_approval", result["promotion_status"])

    def test_real_changed_strategy_uses_candidate_backtest_not_baseline_backtest(self) -> None:
        experiment = build_experiment()
        candidate_backtest = build_real_backtest(experiment, source=MarketDataAvailability.REAL, trade_count=60)
        payload = _baseline_payload(experiment, candidate_backtest, baseline_fixture=False)

        result = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략 연구해줘",
            symbol="005930",
            mode="research",
            baseline=payload,
            external_research=_external_ready(),
        )

        learning = result["autonomous_learning_v2"]
        evidence = learning["promotion_candidate_context"]["authoritative_validation_evidence"]
        self.assertEqual(candidate_backtest.result_id, evidence["backtest_result_id"])
        self.assertTrue(result["candidate_backtest_authoritative"])
        self.assertTrue(result["candidate_strategy_fingerprint_matched"])
        self.assertEqual("requires_human_approval", result["promotion_status"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])

    def test_unimplemented_changed_rule_does_not_fabricate_backtest(self) -> None:
        experiment = build_experiment()
        backtest = build_real_backtest(experiment, source=MarketDataAvailability.REAL)
        payload = _baseline_payload(experiment, backtest, baseline_fixture=False, changed_fields=())

        result = production_autonomous_learning_payload_from_baseline(
            "삼성전자 전략 연구해줘",
            symbol="005930",
            mode="research",
            baseline=payload,
            external_research=_external_ready(),
        )

        blockers = result["autonomous_learning_v2"]["blockers"]
        self.assertIn("hypothesis_unexecutable", blockers)
        self.assertNotEqual("requires_human_approval", result["promotion_status"])

    def test_production_autonomous_learning_execution_release_check_passes(self) -> None:
        payload = production_autonomous_learning_execution_release_check()

        self.assertFalse(payload["production_uses_release_fixture"])
        self.assertTrue(payload["fixture_promotion_blocked"])
        self.assertTrue(payload["candidate_backtest_authoritative"])
        self.assertTrue(payload["candidate_strategy_fingerprint_matched"])
        self.assertTrue(payload["real_data_required"])
        self.assertEqual("pass", payload["safety"])

    def test_hotfix1855_production_external_research_enables_bounded_discovery(self) -> None:
        transport = _ReleaseMetadataTransport()
        external = _run_production_external_research(
            "삼성전자 전략을 처음부터 다시 연구해줘. 외부 연구 자료도 찾아보고 검증해줘.",
            symbol="005930",
            transport=transport,
            storage_root=tempfile.mkdtemp(prefix="gaon-hotfix1855-test-"),
        )

        observability = external["observability"]
        discovery = external["discovery_run"]
        self.assertTrue(observability["network_enabled"])
        self.assertTrue(observability["network_executed"])
        self.assertEqual(1, observability["provider_calls"])
        self.assertEqual(1, transport.calls)
        self.assertEqual(list(DEFAULT_ALLOWED_API_HOSTS), observability["allowed_api_hosts"])
        self.assertTrue(discovery["network_enabled"])
        self.assertNotEqual("network_disabled", observability["failure_kind"])

    def test_hotfix1855_metadata_only_is_content_unavailable_not_provider_failure(self) -> None:
        external = _run_production_external_research(
            "삼성전자 외부 연구 자료를 찾아서 검증해줘.",
            symbol="005930",
            transport=_ReleaseMetadataTransport(),
            storage_root=tempfile.mkdtemp(prefix="gaon-hotfix1855-test-"),
        )

        self.assertEqual("content_unavailable", external["state"])
        self.assertEqual(0, external["acquired_sources"])
        self.assertEqual([], external["candidates"])
        self.assertEqual("metadata_only", external["observability"]["content_acquisition_state"])
        self.assertEqual("metadata_only", external["observability"]["terminal_state"])

    def test_hotfix1855_metadata_only_cannot_promote_candidate(self) -> None:
        experiment = build_experiment()
        candidate_backtest = build_real_backtest(experiment, source=MarketDataAvailability.REAL, trade_count=60)
        baseline = _baseline_payload(experiment, candidate_backtest, baseline_fixture=False)
        external = _run_production_external_research(
            "삼성전자 외부 연구 자료를 찾아서 후보를 검증해줘.",
            symbol="005930",
            transport=_ReleaseMetadataTransport(),
            storage_root=tempfile.mkdtemp(prefix="gaon-hotfix1855-test-"),
        )

        payload = production_autonomous_learning_payload_from_baseline(
            "삼성전자 외부 연구 자료를 찾아서 후보를 검증해줘.",
            symbol="005930",
            mode="research",
            baseline=baseline,
            external_research=external,
        )

        self.assertEqual("needs_real_validation", payload["promotion_status"])
        self.assertFalse(payload["approval_required"])
        self.assertTrue(payload["fixture_promotion_blocked"])
        self.assertIn("external_research_content_unavailable", payload["autonomous_learning_v2"]["blockers"])

    def test_hotfix1855_provider_failure_is_distinct_from_content_unavailable(self) -> None:
        external = _run_production_external_research(
            "삼성전자 외부 연구 자료를 찾아줘.",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode="provider_failure"),
            storage_root=tempfile.mkdtemp(prefix="gaon-hotfix1855-test-"),
        )

        self.assertEqual("provider_failure", external["state"])
        self.assertEqual("provider_failure", external["observability"]["terminal_state"])
        self.assertEqual("timeout", external["observability"]["failure_kind"])

    def test_hotfix1855_no_results_is_no_new_research_path(self) -> None:
        external = _run_production_external_research(
            "삼성전자 외부 연구 자료를 찾아줘.",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode="no_results"),
            storage_root=tempfile.mkdtemp(prefix="gaon-hotfix1855-test-"),
        )

        self.assertEqual("no_new_research_path", external["state"])
        self.assertTrue(external["network_executed"])
        self.assertEqual(0, len(external["discovery_run"]["results"]))

    def test_hotfix1855_disabled_discovery_is_not_reported_as_provider_failure(self) -> None:
        external = _run_production_external_research(
            "삼성전자 외부 연구 자료를 찾아줘.",
            symbol="005930",
            transport=_ReleaseMetadataTransport(),
            network_enabled=False,
            storage_root=tempfile.mkdtemp(prefix="gaon-hotfix1855-test-"),
        )

        self.assertEqual("discovery_network_disabled", external["state"])
        self.assertIn("discovery_network_disabled", external["blockers"])
        self.assertFalse(external["observability"]["network_executed"])

    def test_hotfix1855_network_host_policy_stays_allowlisted(self) -> None:
        with self.assertRaises(ValueError):
            NetworkExecutionPolicy(network_enabled=True, allowed_api_hosts=("api.crossref.org/path",))
        external = _run_production_external_research(
            "삼성전자 외부 연구 자료를 찾아줘.",
            symbol="005930",
            transport=_ReleaseMetadataTransport(),
            storage_root=tempfile.mkdtemp(prefix="gaon-hotfix1855-test-"),
        )
        self.assertEqual(list(DEFAULT_ALLOWED_API_HOSTS), external["observability"]["allowed_api_hosts"])

    def test_production_external_research_network_release_check_passes(self) -> None:
        payload = production_external_research_network_release_check()

        self.assertTrue(payload["discovery_network_explicitly_enabled"])
        self.assertTrue(payload["provider_allowlist_preserved"])
        self.assertTrue(payload["metadata_discovery_executed"])
        self.assertTrue(payload["metadata_only_not_claimed_as_content"])
        self.assertTrue(payload["content_unavailable_not_provider_failure"])
        self.assertTrue(payload["fixture_promotion_blocked"])
        self.assertEqual("pass", payload["safety"])


def _baseline_payload(experiment, candidate_backtest, *, baseline_fixture: bool, changed_fields=("entry.breakout_lookback",)) -> dict[str, object]:
    strategy = candidate_backtest.strategy.to_json()
    source = "fixture" if baseline_fixture else "real"
    baseline_backtest = candidate_backtest.to_json()
    baseline_backtest["source"] = source
    candidate_result = candidate_backtest.to_json()
    return {
        "schema_version": 1,
        "report_id": "krx-real-research-report:test",
        "run_id": "krx-real-research:test",
        "dataset": {
            "metadata": {
                "source": "fixture:krx-real-research" if baseline_fixture else "real:yahoo-chart",
                "fixture_backed": baseline_fixture,
                "start_date": experiment.start,
                "end_date": experiment.end,
                "rows": 1200,
            }
        },
        "quality": {"status": "pass", "findings": []},
        "strategy": {"spec_id": "strategy:baseline", "fingerprint": experiment.baseline_strategy_fingerprint},
        "assumptions": candidate_backtest.assumptions.to_json(),
        "backtest": baseline_backtest,
        "candidates": [
            {
                "candidate_id": "candidate:test",
                "parent_strategy_id": "strategy:baseline",
                "strategy": strategy,
                "changed_fields": list(changed_fields),
                "reason_ko": "verified candidate",
                "provenance": "research_candidate",
                "backtest_result": candidate_result,
            }
        ],
    }


def _external_ready() -> dict[str, object]:
    return {
        "schema_version": 1,
        "state": "evidence_sufficient",
        "question_id": "research-question:test",
        "discovery_run": {
            "results": [
                {
                    "result_id": "discovery:test",
                    "title": "Real provider metadata",
                    "source_type": "research_report",
                    "locator": "https://doi.org/10.0000/example",
                }
            ]
        },
        "normalized_records": [],
        "candidates": [{"candidate_id": "claim:test", "source_id": "source:test"}],
        "blockers": [],
        "network_executed": False,
    }


if __name__ == "__main__":
    unittest.main()
