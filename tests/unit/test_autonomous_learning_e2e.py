from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from gaon.knowledge.autonomous_learning_e2e import autonomous_learning_e2e_release_check
from gaon.knowledge.conflicts import ConflictStatus
from gaon.knowledge.content_acquisition import ContentAcquisitionPolicy
from gaon.knowledge.discovery import DiscoveryProvider, DiscoveryResult, DiscoveryStatus
from gaon.knowledge.external_research_execution import AcademicContentResolver, AcademicRelevanceScreener, ContentResolutionStatus, _validate_doi_resolution_hop
from gaon.knowledge.execution import DEFAULT_ALLOWED_API_HOSTS, NetworkExecutionPolicy
from gaon.knowledge.telegram_autonomous_learning import (
    _ReleaseDoiResolutionTransport,
    _ReleaseContentTransport,
    _ReleaseMetadataTransport,
    _run_production_external_research,
    autonomous_learning_safe_failure_payload,
    production_authoritative_candidate_validation_release_check,
    production_academic_source_budget_release_check,
    production_academic_source_fallback_release_check,
    production_autonomous_learning_execution_release_check,
    production_autonomous_learning_loop_release_check,
    production_autonomous_learning_state_semantics_release_check,
    production_evidence_backed_hypothesis_release_check,
    production_external_research_network_release_check,
    production_grounded_evidence_release_check,
    production_human_promotion_gate_release_check,
    production_relevant_academic_content_loop_release_check,
    production_relevant_academic_discovery_release_check,
    production_real_academic_content_resolution_release_check,
    production_robustness_ranking_release_check,
    production_safe_doi_redirect_release_check,
    production_safe_content_acquisition_release_check,
    production_strategy_experiment_release_check,
    production_autonomous_learning_payload_from_baseline,
    telegram_autonomous_learning_payload,
)
from gaon.knowledge.gaps import KnowledgeGapType, RequiredEvidence, RequiredEvidenceType, ResearchPriority, ResearchQuestion, ResearchStopCondition
from gaon.knowledge.provenance import SourceType
from gaon.research.krx_real_pipeline import MarketDataAvailability
from gaon.runtime.llm_tools import SafeToolExecutor, ToolDefinition, ToolRegistry, ToolRequest, ToolRiskLevel
from gaon.runtime.storage import RuntimeStateStore
from gaon.storage.foundation import resolve_data_root
from tests.fixtures.knowledge_pipeline import build_experiment, build_real_backtest


class AutonomousLearningE2EReleaseCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._storage_tmp = tempfile.TemporaryDirectory(prefix="gaon-hotfix1855-class-")
        self._old_storage_root = os.environ.get("GAON_EXTERNAL_RESEARCH_STORAGE_ROOT")
        os.environ["GAON_EXTERNAL_RESEARCH_STORAGE_ROOT"] = self._storage_tmp.name

    def tearDown(self) -> None:
        if self._old_storage_root is None:
            os.environ.pop("GAON_EXTERNAL_RESEARCH_STORAGE_ROOT", None)
        else:
            os.environ["GAON_EXTERNAL_RESEARCH_STORAGE_ROOT"] = self._old_storage_root
        self._storage_tmp.cleanup()

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
            with tempfile.TemporaryDirectory(prefix="gaon-hotfix1855-wrapper-") as tmp:
                payload = telegram_autonomous_learning_payload(
                store._connection,
                "삼성전자 전략을 처음부터 다시 연구해줘",
                    symbol="005930",
                    storage_root=tmp,
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

    def test_hotfix1855_production_storage_default_remains_unchanged(self) -> None:
        self.assertEqual(Path("/var/lib/strategylab/gaon-data"), resolve_data_root(env={}, system="Linux"))

    def test_hotfix1855_injected_storage_is_used_and_cleaned_up(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gaon-hotfix1855-cleanup-") as tmp:
            root = Path(tmp)
            external = _run_production_external_research(
                "삼성전자 외부 연구 자료를 찾아줘.",
            symbol="005930",
            transport=_ReleaseMetadataTransport(),
            content_network_enabled=False,
            storage_root=tmp,
        )
            self.assertEqual("content_unavailable", external["state"])
            self.assertTrue((root / "knowledge").exists())
            self.assertFalse(Path("/var/lib/strategylab").exists() and (root == Path("/var/lib/strategylab")))
            saved_root = root
        self.assertFalse(saved_root.exists())

    def test_hotfix1855_production_external_research_enables_bounded_discovery(self) -> None:
        transport = _ReleaseMetadataTransport()
        external = _run_production_external_research(
            "삼성전자 전략을 처음부터 다시 연구해줘. 외부 연구 자료도 찾아보고 검증해줘.",
            symbol="005930",
            transport=transport,
            content_network_enabled=False,
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
            content_network_enabled=False,
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
            content_network_enabled=False,
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
            content_network_enabled=False,
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
            content_network_enabled=False,
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
            content_network_enabled=False,
            network_enabled=False,
            storage_root=tempfile.mkdtemp(prefix="gaon-hotfix1855-test-"),
        )

        self.assertEqual("discovery_network_disabled", external["state"])
        self.assertIn("discovery_network_disabled", external["blockers"])
        self.assertFalse(external["observability"]["network_executed"])

    def test_hotfix1855_safe_failure_payload_preserves_top_level_contract(self) -> None:
        payload = autonomous_learning_safe_failure_payload(
            "삼성전자 외부 연구 자료를 찾아서 검증해줘.",
            symbol="005930",
            error_type="PermissionError",
            message="permission denied",
        )

        self.assertFalse(payload["production_uses_release_fixture"])
        self.assertTrue(payload["fixture_promotion_blocked"])
        self.assertFalse(payload["candidate_backtest_authoritative"])
        self.assertFalse(payload["candidate_strategy_fingerprint_matched"])
        self.assertTrue(payload["real_data_required"])
        self.assertFalse(payload["approval_required"])
        self.assertEqual("needs_real_validation", payload["promotion_status"])
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["broker_order_called"])
        self.assertFalse(payload["kis_order_called"])
        self.assertEqual("pass", payload["safety"])

    def test_hotfix1855_safe_tool_failure_preserves_autonomous_learning_contract(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "autonomous_learning_research",
                "test autonomous learning failure",
                ToolRiskLevel.READ_ONLY,
                required_args=("request_text",),
                allowed_args=("symbol", "mode"),
            ),
            lambda _args: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
        )
        result = SafeToolExecutor(registry).execute(
            ToolRequest(
                "autonomous_learning_research",
                {"request_text": "삼성전자 외부 연구 자료를 찾아서 검증해줘.", "symbol": "005930"},
                "tester",
                "2026-08-08T00:00:00Z",
            )
        )

        self.assertEqual("denied", result.status)
        self.assertFalse(result.output["production_uses_release_fixture"])
        self.assertTrue(result.output["fixture_promotion_blocked"])
        self.assertFalse(result.output["approval_required"])
        self.assertEqual("needs_real_validation", result.output["promotion_status"])
        self.assertFalse(result.output["strategy_mutated"])
        self.assertFalse(result.output["order_executed"])
        self.assertFalse(result.output["broker_order_called"])
        self.assertFalse(result.output["kis_order_called"])

    def test_hotfix1855_network_host_policy_stays_allowlisted(self) -> None:
        with self.assertRaises(ValueError):
            NetworkExecutionPolicy(network_enabled=True, allowed_api_hosts=("api.crossref.org/path",))
        external = _run_production_external_research(
            "삼성전자 외부 연구 자료를 찾아줘.",
            symbol="005930",
            transport=_ReleaseMetadataTransport(),
            content_network_enabled=False,
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

    def test_sprint186_allowed_content_acquisition_creates_evidence(self) -> None:
        external = _run_production_external_research(
            "Samsung breakout strategy external evidence safe content acquisition",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode="direct_content"),
            content_transport=_ReleaseContentTransport(),
            allowed_content_hosts=("content.example.org",),
            storage_root=tempfile.mkdtemp(prefix="gaon-sprint186-test-"),
        )

        observability = external["observability"]
        self.assertEqual("content_acquired", observability["content_acquisition_state"])
        self.assertEqual(1, external["acquired_sources"])
        self.assertTrue(external["normalized_records"])
        self.assertTrue(external["candidates"])
        self.assertEqual("text/html", observability["content_sources"][0]["content_type"])
        self.assertEqual(64, len(observability["content_sources"][0]["content_sha256"]))

    def test_sprint186_arbitrary_content_host_is_blocked(self) -> None:
        external = _run_production_external_research(
            "blocked host external research",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode="direct_content"),
            content_transport=_ReleaseContentTransport(),
            allowed_content_hosts=("other.example.org",),
            storage_root=tempfile.mkdtemp(prefix="gaon-sprint186-test-"),
        )

        self.assertEqual("content_blocked", external["observability"]["content_acquisition_state"])
        self.assertFalse(external["candidates"])

    def test_sprint186_unsupported_mime_and_byte_limit_fail_closed(self) -> None:
        unsupported = _run_production_external_research(
            "unsupported mime external research",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode="direct_content"),
            content_transport=_ReleaseContentTransport(content_type="application/octet-stream"),
            allowed_content_hosts=("content.example.org",),
            storage_root=tempfile.mkdtemp(prefix="gaon-sprint186-test-"),
        )
        oversized = _run_production_external_research(
            "oversized external research",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode="direct_content"),
            content_transport=_ReleaseContentTransport(content=b"x" * 262145),
            allowed_content_hosts=("content.example.org",),
            storage_root=tempfile.mkdtemp(prefix="gaon-sprint186-test-"),
        )

        self.assertEqual("unsupported_content_type", unsupported["observability"]["content_acquisition_state"])
        self.assertEqual("content_blocked", oversized["observability"]["content_acquisition_state"])
        self.assertFalse(unsupported["candidates"])
        self.assertFalse(oversized["candidates"])

    def test_sprint186_timeout_failure_is_not_promotable(self) -> None:
        external = _run_production_external_research(
            "timeout external research",
            symbol="005930",
            transport=_ReleaseMetadataTransport(mode="direct_content"),
            content_transport=_ReleaseContentTransport(failure=TimeoutError("timeout")),
            allowed_content_hosts=("content.example.org",),
            storage_root=tempfile.mkdtemp(prefix="gaon-sprint186-test-"),
        )
        result = production_autonomous_learning_payload_from_baseline(
            "timeout external research",
            symbol="005930",
            mode="research",
            baseline=_baseline_payload(build_experiment(), build_real_backtest(build_experiment(), source=MarketDataAvailability.REAL), baseline_fixture=False),
            external_research=external,
        )

        self.assertEqual("fetch_failure", external["observability"]["content_acquisition_state"])
        self.assertFalse(result["approval_required"])
        self.assertEqual("needs_real_validation", result["promotion_status"])

    def test_sprint186_release_check_passes(self) -> None:
        payload = production_safe_content_acquisition_release_check()

        self.assertEqual("content_acquired", payload["content_acquisition_state"])
        self.assertTrue(payload["metadata_only_evidence_blocked"])
        self.assertTrue(payload["fixture_promotion_blocked"])
        self.assertEqual("pass", payload["safety"])

    def test_sprint187_grounded_evidence_release_check_passes(self) -> None:
        payload = production_grounded_evidence_release_check()

        self.assertEqual("grounded_evidence", payload["stage"])
        self.assertGreaterEqual(payload["grounded_evidence_count"], 1)
        self.assertEqual("pass", payload["safety"])

    def test_sprint188_evidence_backed_hypothesis_release_check_passes(self) -> None:
        payload = production_evidence_backed_hypothesis_release_check()

        self.assertEqual("evidence_backed_hypothesis", payload["stage"])
        self.assertGreaterEqual(payload["hypothesis_count"], 1)
        self.assertEqual("pass", payload["safety"])

    def test_sprint189_strategy_experiment_release_check_passes(self) -> None:
        payload = production_strategy_experiment_release_check()

        self.assertEqual("strategy_experiment", payload["stage"])
        self.assertGreaterEqual(payload["candidate_experiment_count"], 1)
        self.assertEqual("pass", payload["safety"])

    def test_sprint190_authoritative_candidate_validation_release_check_passes(self) -> None:
        payload = production_authoritative_candidate_validation_release_check()

        self.assertEqual("authoritative_candidate_validation", payload["stage"])
        self.assertEqual("pass", payload["safety"])

    def test_sprint191_robustness_ranking_release_check_passes(self) -> None:
        payload = production_robustness_ranking_release_check()

        self.assertEqual("robustness_ranking", payload["stage"])
        self.assertEqual("pass", payload["safety"])

    def test_sprint192_human_promotion_gate_release_check_passes(self) -> None:
        payload = production_human_promotion_gate_release_check()

        self.assertEqual("human_promotion_gate", payload["stage"])
        self.assertEqual("requires_human_approval", payload["promotion_status"])
        self.assertEqual("awaiting_human_approval", payload["human_gate_status"])
        self.assertEqual("pass", payload["safety"])

    def test_sprint187_192_integrated_loop_release_check_passes(self) -> None:
        payload = production_autonomous_learning_loop_release_check()

        self.assertEqual("production_autonomous_learning_loop", payload["stage"])
        self.assertGreaterEqual(payload["grounded_evidence_count"], 1)
        self.assertGreaterEqual(payload["hypothesis_count"], 1)
        self.assertGreaterEqual(payload["candidate_experiment_count"], 1)
        self.assertEqual("requires_human_approval", payload["promotion_status"])
        self.assertEqual("pass", payload["safety"])

    def test_sprint187_metadata_only_cannot_create_grounded_evidence(self) -> None:
        experiment = build_experiment()
        candidate_backtest = build_real_backtest(experiment, source=MarketDataAvailability.REAL, trade_count=60)
        payload = production_autonomous_learning_payload_from_baseline(
            "metadata only external research",
            symbol="005930",
            mode="research",
            baseline=_baseline_payload(experiment, candidate_backtest, baseline_fixture=False),
            external_research={
                "schema_version": 1,
                "state": "content_unavailable",
                "discovery_run": {"results": [{"result_id": "discovery:metadata", "locator": "https://doi.org/10.0000/metadata"}]},
                "normalized_records": [],
                "acquisition_records": [],
                "candidates": [{"candidate_id": "claim:metadata", "source_id": "source:metadata"}],
                "blockers": ["content_unavailable"],
            },
        )

        learning = payload["autonomous_learning_v2"]
        self.assertEqual([], learning["grounded_evidence"])
        self.assertEqual("needs_real_validation", payload["promotion_status"])
        self.assertIn("grounded_evidence_unavailable", learning["blockers"])

    def test_hotfix1921_academic_resolver_handles_doi_and_resource_links(self) -> None:
        resolver = AcademicContentResolver(
            policy=ContentAcquisitionPolicy(
                network_enabled=True,
                allowed_hosts=("doi.org", "content.example.org"),
            ),
            doi_transport=_ReleaseDoiResolutionTransport(),
        )
        doi_result = _discovery_result("https://doi.org/10.1234/example", doi="10.1234/example")
        resource_result = _discovery_result(
            "https://doi.org/10.1234/resource",
            doi="10.1234/resource",
            metadata_resource_url="https://content.example.org/research.html",
        )

        doi_resolution = resolver.resolve(doi_result)
        resource_resolution = resolver.resolve(resource_result)

        self.assertEqual(ContentResolutionStatus.DOI_RESOLVED, doi_resolution.status)
        self.assertEqual("doi_url", doi_resolution.locator_kind)
        self.assertEqual("content.example.org", doi_resolution.final_host)
        self.assertEqual(ContentResolutionStatus.METADATA_RESOURCE_URL, resource_resolution.status)
        self.assertEqual("content.example.org", resource_resolution.final_host)

    def test_hotfix1921_academic_resolver_blocks_unsafe_targets(self) -> None:
        resolver = AcademicContentResolver(
            policy=ContentAcquisitionPolicy(
                network_enabled=True,
                allowed_hosts=("doi.org", "content.example.org"),
            ),
            doi_transport=_ReleaseDoiResolutionTransport(final_url="https://blocked-publisher.example/research.html"),
        )
        blocked = resolver.resolve(_discovery_result("https://doi.org/10.1234/blocked", doi="10.1234/blocked"))
        http = AcademicContentResolver(
            policy=ContentAcquisitionPolicy(
                network_enabled=True,
                allowed_hosts=("doi.org", "content.example.org"),
            ),
            doi_transport=_ReleaseDoiResolutionTransport(final_url="http://content.example.org/research.html"),
        ).resolve(_discovery_result("https://doi.org/10.1234/http", doi="10.1234/http"))

        self.assertEqual(ContentResolutionStatus.CONTENT_BLOCKED, blocked.status)
        self.assertEqual("content_blocked", blocked.failure_kind)
        self.assertEqual(ContentResolutionStatus.CONTENT_BLOCKED, http.status)

    def test_hotfix1921_real_academic_content_resolution_release_check_passes(self) -> None:
        payload = production_real_academic_content_resolution_release_check()

        self.assertEqual("doi_url", payload["locator_kind"])
        self.assertEqual("metadata_resource_url", payload["resolution_status"])
        self.assertEqual("content_acquired", payload["content_acquisition_state"])
        self.assertGreaterEqual(payload["grounded_evidence_count"], 1)
        self.assertEqual("pass", payload["safety"])

    def test_hotfix1922_academic_relevance_accepts_trading_metadata(self) -> None:
        screener = AcademicRelevanceScreener()
        result = _discovery_result(
            "https://doi.org/10.1234/trading",
            doi="10.1234/trading",
            title="Financial market trend following and breakout trading rules",
            abstract="Out-of-sample robustness of moving average filters in equity trading.",
        )

        relevance = screener.screen(_academic_question(), result)

        self.assertEqual("relevant", relevance.relevance_status.value)
        self.assertTrue(relevance.selected_for_content_acquisition)
        self.assertIn("financial market", relevance.matched_domain_terms)
        self.assertIn("breakout", relevance.matched_research_terms)

    def test_hotfix1922_academic_relevance_rejects_tuple_recovery_strategy(self) -> None:
        screener = AcademicRelevanceScreener()
        result = _discovery_result(
            "https://doi.org/10.1007/978-3-322-93860-2_11",
            doi="10.1007/978-3-322-93860-2_11",
            title="The Location and Replication Independent Tuple Recovery Strategy",
            abstract="Distributed systems tuple recovery and data replication strategy.",
        )

        relevance = screener.screen(_academic_question(), result)

        self.assertEqual("wrong_domain", relevance.relevance_status.value)
        self.assertFalse(relevance.selected_for_content_acquisition)
        self.assertIn("tuple recovery", relevance.matched_negative_terms)

    def test_hotfix1922_irrelevant_academic_source_is_not_fetched(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gaon-hotfix1922-irrelevant-") as tmp:
            content_transport = _ReleaseContentTransport()
            external = _run_production_external_research(
                "Samsung breakout strategy irrelevant academic source",
                symbol="005930",
                transport=_ReleaseMetadataTransport(mode="irrelevant_tuple"),
                content_transport=content_transport,
                doi_resolution_transport=_ReleaseDoiResolutionTransport(),
                allowed_content_hosts=("content.example.org", "doi.org"),
                storage_root=tmp,
            )

        observability = external["observability"]
        relevance = observability["academic_relevance"]

        self.assertEqual("no_relevant_research_path", external["state"])
        self.assertEqual(0, content_transport.calls)
        self.assertEqual("wrong_domain", relevance[0]["relevance_status"])
        self.assertEqual([], external["candidates"])

    def test_hotfix1922_release_checks_pass(self) -> None:
        self.assertEqual("pass", production_relevant_academic_discovery_release_check()["safety"])
        self.assertEqual("pass", production_safe_doi_redirect_release_check()["safety"])
        self.assertEqual("pass", production_relevant_academic_content_loop_release_check()["safety"])

    def test_hotfix1923_source_fallback_release_check_passes(self) -> None:
        payload = production_academic_source_fallback_release_check()

        self.assertEqual("pass", payload["safety"])
        self.assertEqual(2, payload["resolution_attempt_count"])
        self.assertEqual(1, payload["acquired_source_count"])
        attempts = payload["source_attempts"]
        self.assertEqual("resolution_failure", attempts[0]["failure_kind"])
        self.assertEqual("acquired", attempts[1]["acquisition_status"])

    def test_hotfix1923_budget_and_state_semantics_release_checks_pass(self) -> None:
        budget = production_academic_source_budget_release_check()
        semantics = production_autonomous_learning_state_semantics_release_check()

        self.assertEqual("pass", budget["safety"])
        self.assertTrue(budget["duplicate_skipped"])
        self.assertLessEqual(budget["resolution_attempt_count"], 3)
        self.assertEqual("pass", semantics["safety"])
        self.assertEqual("needs_real_validation", semantics["real_missing_promotion_status"])
        self.assertNotEqual("proposed", semantics["real_missing_hypothesis_status"])
        self.assertEqual("blocked_fixture", semantics["fixture_promotion_status"])

    def test_hotfix1922_safe_doi_redirect_blocks_unsafe_final_targets(self) -> None:
        resolver = AcademicContentResolver(
            policy=ContentAcquisitionPolicy(
                network_enabled=True,
                allowed_hosts=("doi.org", "content.example.org"),
            ),
            doi_transport=_ReleaseDoiResolutionTransport(
                final_url="http://content.example.org/research.html",
                redirect_chain=(
                    "https://doi.org/10.1234/http-final",
                    "http://content.example.org/research.html",
                ),
            ),
        )

        resolution = resolver.resolve(
            _discovery_result("https://doi.org/10.1234/http-final", doi="10.1234/http-final")
        )

        self.assertEqual(ContentResolutionStatus.CONTENT_BLOCKED, resolution.status)
        self.assertEqual("content_blocked", resolution.failure_kind)

    def test_hotfix1922_doi_resolution_hop_policy_allows_public_http_intermediate_only(self) -> None:
        with patch(
            "gaon.knowledge.external_research_execution.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("93.184.216.34", 80))],
        ):
            _validate_doi_resolution_hop("http://doi-proxy.example.org/temporary")

        with self.assertRaises(PermissionError):
            _validate_doi_resolution_hop("http://127.0.0.1/temporary")

        with self.assertRaises(PermissionError):
            _validate_doi_resolution_hop("ftp://doi-proxy.example.org/temporary")


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
        "grounded_evidence": [
            {
                "evidence_id": "grounded-evidence:test",
                "claim_id": "claim:test",
                "source_id": "source:test",
                "source_locator": "https://doi.org/10.0000/example",
                "content_type": "text/html",
                "content_sha256": "1" * 64,
                "verbatim_excerpt": "Breakout filters can reduce false signals.",
                "metadata_only": False,
                "fixture_backed": False,
                "grounded": True,
            }
        ],
        "blockers": [],
        "network_executed": False,
    }


def _discovery_result(
    locator: str,
    *,
    doi: str | None = None,
    metadata_resource_url: str | None = None,
    title: str = "Academic resolver test",
    abstract: str | None = None,
) -> DiscoveryResult:
    return DiscoveryResult(
        result_id=f"discovery-result:test:{abs(hash(locator))}",
        query_id="query:test",
        provider=DiscoveryProvider.ACADEMIC_SEARCH,
        title=title,
        locator=locator,
        source_type=SourceType.ACADEMIC_PAPER,
        status=DiscoveryStatus.DISCOVERED,
        doi=doi,
        metadata_resource_url=metadata_resource_url,
        abstract=abstract,
    )


def _academic_question() -> ResearchQuestion:
    return ResearchQuestion(
        question_id="research-question:hotfix1922",
        topic_key="strategy.breakout.robustness",
        gap_type=KnowledgeGapType.INSUFFICIENT_INDEPENDENCE,
        question=(
            "financial markets breakout trend following trading rules "
            "moving average volume confirmation stop-loss trailing exit "
            "out-of-sample robustness evidence"
        ),
        priority=ResearchPriority.MEDIUM,
        required_evidence=(
            RequiredEvidence(
                evidence_type=RequiredEvidenceType.INDEPENDENT_SUPPORTING_SOURCE,
                minimum_independent_sources=1,
                rationale="test",
            ),
        ),
        stop_conditions=(ResearchStopCondition.EVIDENCE_BUDGET_EXHAUSTED,),
        parent_conflict_id="knowledge-conflict:hotfix1922",
        source_state=ConflictStatus.UNRESOLVED_CONFLICT,
    )


if __name__ == "__main__":
    unittest.main()
