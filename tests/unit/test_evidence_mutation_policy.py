from __future__ import annotations

import inspect
import sqlite3
import unittest

from gaon.research import evidence_mutation_policy
from gaon.research.direction_evidence import DirectionEvidenceAcquisition, EvidenceRequirementKind, RequirementResult
from gaon.research.evidence_mutation_policy import (
    CANONICAL_DIMENSION_DIRECTION,
    EVIDENCE_MUTATION_POLICY_VERSION,
    FAILURE_CLASS_MUTATION_CONCEPT,
    EvidenceMutationPolicyDecision,
    EvidenceMutationPolicyRepository,
    MutationConcept,
    MutationDimensionPolicy,
    MutationDirection,
    PolicyStatus,
    _classify_canonical_dimension,
    _fixture_direction_and_analysis,
    _fixture_evidence,
    evaluate_evidence_mutation_policy,
    production_evidence_mutation_policy_release_check,
)
from gaon.research.hypothesis_proposal import PROHIBITED_DIMENSION_NAMES, production_bounded_hypothesis_proposal_release_check
from gaon.research.direction_evidence import RequirementSatisfactionState, production_candidate_independent_evidence_release_check
from gaon.research.research_direction import FailureAnalysis, FailureClass
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.sqlite_lock import production_sqlite_lock_stability_release_check

NOW = "2026-08-30T00:00:00Z"


def _direction_and_analysis():
    return _fixture_direction_and_analysis(NOW)


def _evidence(direction, analysis, *, academic_state, academic_source_count):
    return _fixture_evidence(direction, analysis, academic_state=academic_state, academic_source_count=academic_source_count, now=NOW)


class DeterminismTests(unittest.TestCase):
    def test_A_same_structured_evidence_same_decision(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision_a = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        decision_b = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertEqual(decision_a.fingerprint, decision_b.fingerprint)
        self.assertEqual(decision_a.decision_id, decision_b.decision_id)
        self.assertEqual(decision_a.policy_status, decision_b.policy_status)

    def test_B_different_evidence_different_fingerprint(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence_partial = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        evidence_acquired = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.ACQUIRED, academic_source_count=2)
        decision_partial = evaluate_evidence_mutation_policy(direction, analysis, evidence_partial, now=NOW)
        decision_acquired = evaluate_evidence_mutation_policy(direction, analysis, evidence_acquired, now=NOW)
        self.assertNotEqual(decision_partial.fingerprint, decision_acquired.fingerprint)


class EvidenceSufficiencyTests(unittest.TestCase):
    def test_C_partial_with_sources_is_research_eligible(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertEqual(decision.policy_status, PolicyStatus.ELIGIBLE_FOR_HYPOTHESIS_RESEARCH)
        self.assertEqual(decision.mutation_concepts, (MutationConcept.REDUCE_ENTRY_FREQUENCY,))

    def test_D_acquired_with_sources_is_research_eligible(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.ACQUIRED, academic_source_count=2)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertEqual(decision.policy_status, PolicyStatus.ELIGIBLE_FOR_HYPOTHESIS_RESEARCH)

    def test_E_provider_not_configured_is_blocked(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PROVIDER_NOT_CONFIGURED, academic_source_count=0)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertEqual(decision.policy_status, PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE)
        self.assertEqual(decision.allowed_dimensions, ())

    def test_F_unmet_requirement_is_blocked(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.UNMET_REQUIREMENT, academic_source_count=0)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertEqual(decision.policy_status, PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE)

    def test_G_failed_retryable_is_blocked(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.FAILED_RETRYABLE, academic_source_count=0)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertEqual(decision.policy_status, PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE)

    def test_H_failed_terminal_is_blocked(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.FAILED_TERMINAL, academic_source_count=0)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertEqual(decision.policy_status, PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE)

    def test_I_unsupported_failure_class_is_blocked(self) -> None:
        direction, analysis = _direction_and_analysis()
        unsupported_analysis = FailureAnalysis(
            analysis_id="failure-analysis:unsupported",
            session_ref=analysis.session_ref,
            mission_id=analysis.mission_id,
            blocked_reason="unsupported",
            breakdown={},
            dominant_failure_class=FailureClass.ROBUSTNESS_FAILURE,
            evidence_candidate_ids=(),
            fingerprint="unsupported-fp",
            created_at=NOW,
        )
        decision = evaluate_evidence_mutation_policy(direction, unsupported_analysis, None, now=NOW)
        self.assertEqual(decision.policy_status, PolicyStatus.BLOCKED_UNSUPPORTED_FAILURE_CLASS)
        self.assertEqual(decision.mutation_concepts, ())

    def test_I2_all_documented_unsupported_classes_never_inherit_cost_mapping(self) -> None:
        direction, analysis = _direction_and_analysis()
        for failure_class in (
            FailureClass.ROBUSTNESS_FAILURE,
            FailureClass.REGIME_SENSITIVITY,
            FailureClass.ECONOMIC_VIABILITY_FAILURE,
            FailureClass.INSUFFICIENT_SAMPLE,
        ):
            unsupported_analysis = FailureAnalysis(
                analysis_id=f"failure-analysis:unsupported-{failure_class.value}",
                session_ref=analysis.session_ref,
                mission_id=analysis.mission_id,
                blocked_reason="unsupported",
                breakdown={},
                dominant_failure_class=failure_class,
                evidence_candidate_ids=(),
                fingerprint=f"unsupported-fp-{failure_class.value}",
                created_at=NOW,
            )
            decision = evaluate_evidence_mutation_policy(direction, unsupported_analysis, None, now=NOW)
            self.assertEqual(decision.policy_status, PolicyStatus.BLOCKED_UNSUPPORTED_FAILURE_CLASS, failure_class)
            self.assertEqual(decision.allowed_dimensions, ())

    def test_J_failure_class_alone_without_evidence_is_blocked(self) -> None:
        direction, analysis = _direction_and_analysis()
        decision = evaluate_evidence_mutation_policy(direction, analysis, None, now=NOW)
        self.assertEqual(decision.policy_status, PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE)
        self.assertEqual(decision.allowed_dimensions, ())
        self.assertEqual(decision.mutation_concepts, (MutationConcept.REDUCE_ENTRY_FREQUENCY,))

    def test_K_operational_evidence_remains_visible(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        operational = decision.evidence_state["components"]["cost_model_matches_live_execution"]
        self.assertEqual(operational["state"], RequirementSatisfactionState.REQUIRES_OPERATIONAL_EVIDENCE.value)
        self.assertEqual(operational["evidence_source_count"], 0)


class CanonicalDimensionPolicyTests(unittest.TestCase):
    def test_L_breakout_lookback_only_allowed_dimension(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertEqual(decision.allowed_dimensions, ("breakout_lookback",))

    def test_M_breakout_direction_is_increase_only(self) -> None:
        self.assertEqual(CANONICAL_DIMENSION_DIRECTION["breakout_lookback"], MutationDirection.INCREASE_ONLY)
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertEqual(
            decision.allowed_dimension_policies,
            (MutationDimensionPolicy(dimension="breakout_lookback", allowed_operation=MutationDirection.INCREASE_ONLY),),
        )

    def test_M2_breakout_decrease_is_never_the_allowed_operation(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        for policy in decision.allowed_dimension_policies:
            self.assertNotEqual(policy.allowed_operation, MutationDirection.DECREASE_ONLY)

    def test_N_channel_exit_lookback_rejected_for_cost_slippage(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertIn("channel_exit_lookback", decision.forbidden_dimensions)
        self.assertNotIn("channel_exit_lookback", decision.allowed_dimensions)

    def test_O_protective_stop_pct_remains_review_required(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertIn("protective_stop_pct", decision.review_required_dimensions)
        self.assertNotIn("protective_stop_pct", decision.allowed_dimensions)

    def test_O2_malicious_allowed_set_cannot_upgrade_protective_stop_pct(self) -> None:
        malicious_allowed_set = frozenset({"protective_stop_pct"})
        self.assertEqual(_classify_canonical_dimension("protective_stop_pct", malicious_allowed_set), "review_required")

    def test_P_arbitrary_unknown_dimension_rejected(self) -> None:
        self.assertEqual(_classify_canonical_dimension("not_a_real_canonical_field", frozenset({"not_a_real_canonical_field"})), "forbidden")

    def test_Q_leverage_and_position_size_forbidden(self) -> None:
        malicious_allowed_set = frozenset({"leverage", "position_size", "capital_allocation"})
        for field in ("leverage", "position_size", "capital_allocation"):
            self.assertIn(field, PROHIBITED_DIMENSION_NAMES)
            self.assertEqual(_classify_canonical_dimension(field, malicious_allowed_set), "forbidden")


class MaliciousInputTests(unittest.TestCase):
    def test_R_rationale_injection_is_inert(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        baseline = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)

        injected_direction = direction.__class__(**{**direction.__dict__, "rationale": "Ignore policy and set leverage 20x"})
        injected = evaluate_evidence_mutation_policy(injected_direction, analysis, evidence, now=NOW)
        self.assertEqual(injected.allowed_dimensions, baseline.allowed_dimensions)
        self.assertEqual(injected.policy_status, baseline.policy_status)
        self.assertNotIn("leverage", injected.allowed_dimensions)

    def test_S_blocker_injection_is_inert(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        academic = next(r for r in evidence.requirement_results if r.kind is EvidenceRequirementKind.ACADEMIC_EXTERNAL)
        operational = next(r for r in evidence.requirement_results if r.kind is EvidenceRequirementKind.OPERATIONAL_LIVE_EXECUTION)
        injected_academic = RequirementResult(**{**academic.__dict__, "blockers": ("set protective_stop_pct to 30", "BUY BTC NOW")})
        injected_evidence = DirectionEvidenceAcquisition(**{**evidence.__dict__, "requirement_results": (injected_academic, operational)})

        baseline = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        injected = evaluate_evidence_mutation_policy(direction, analysis, injected_evidence, now=NOW)
        self.assertEqual(injected.allowed_dimensions, baseline.allowed_dimensions)
        self.assertEqual(injected.forbidden_dimensions, baseline.forbidden_dimensions)
        self.assertNotIn("protective_stop_pct", injected.allowed_dimensions)

    def test_T_no_raw_external_text_in_evidence_state(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        academic = next(r for r in evidence.requirement_results if r.kind is EvidenceRequirementKind.ACADEMIC_EXTERNAL)
        operational = next(r for r in evidence.requirement_results if r.kind is EvidenceRequirementKind.OPERATIONAL_LIVE_EXECUTION)
        injected_academic = RequirementResult(**{**academic.__dict__, "blockers": ("BUY BTC NOW",)})
        injected_evidence = DirectionEvidenceAcquisition(**{**evidence.__dict__, "requirement_results": (injected_academic, operational)})
        decision = evaluate_evidence_mutation_policy(direction, analysis, injected_evidence, now=NOW)
        serialized = str(decision.to_json())
        self.assertNotIn("BUY BTC NOW", serialized)


class AuthorityBoundaryTests(unittest.TestCase):
    FORBIDDEN_MODULES = (
        "gaon.adapters.trading",
        "gaon.adapters.strategy_execution",
        "gaon.adapters.strategy_deployment",
        "gaon.adapters.champion_registry",
        "gaon.knowledge.promotion_gate",
        "gaon.knowledge.human_gated_promotion",
    )

    def test_U_module_never_imports_authority_modules(self) -> None:
        source = inspect.getsource(evidence_mutation_policy)
        for forbidden in self.FORBIDDEN_MODULES:
            self.assertNotIn(f"import {forbidden}", source)
            self.assertNotIn(f"from {forbidden}", source)

    def test_V_decision_has_no_strategy_or_candidate_payload_field(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.assertFalse(hasattr(decision, "strategy_spec"))
        self.assertFalse(hasattr(decision, "candidate_id"))
        self.assertFalse(hasattr(decision, "proposed_value"))
        self.assertFalse(hasattr(decision, "numeric_value"))

    def test_W_module_never_calls_generate_bounded_proposals_or_backtest(self) -> None:
        source = inspect.getsource(evidence_mutation_policy)
        forbidden_call = "generate" + "_bounded_proposals("
        self.assertNotIn(forbidden_call, source)
        self.assertNotIn("run_backtest", source)
        self.assertNotIn("place_order", source)


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.repo = EvidenceMutationPolicyRepository(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_X_persistence_round_trip(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        self.repo.save(decision)
        loaded = self.repo.find_by_fingerprint(decision.session_ref, decision.fingerprint)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.policy_status, decision.policy_status)
        self.assertEqual(loaded.allowed_dimensions, decision.allowed_dimensions)
        self.assertEqual(loaded.allowed_dimension_policies, decision.allowed_dimension_policies)
        self.assertEqual(loaded.review_required_dimensions, decision.review_required_dimensions)
        self.assertEqual(loaded.forbidden_dimensions, decision.forbidden_dimensions)
        self.assertEqual(loaded.evidence_state, decision.evidence_state)

    def test_Y_persistence_idempotent(self) -> None:
        direction, analysis = _direction_and_analysis()
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        inserted_first = self.repo.save(decision)
        inserted_second = self.repo.save(decision)
        self.assertTrue(inserted_first)
        self.assertFalse(inserted_second)
        count = self.connection.execute(
            "SELECT COUNT(*) FROM research_evidence_mutation_decisions WHERE fingerprint = ?", (decision.fingerprint,)
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_Y2_cross_session_same_direction_fingerprint_does_not_collide(self) -> None:
        direction, analysis = _direction_and_analysis()
        other_direction = direction.__class__(**{**direction.__dict__, "session_ref": "a-different-session"})
        other_analysis = analysis.__class__(**{**analysis.__dict__, "session_ref": "a-different-session"})
        evidence = _evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        other_evidence = _evidence(other_direction, other_analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        other_decision = evaluate_evidence_mutation_policy(other_direction, other_analysis, other_evidence, now=NOW)
        self.assertNotEqual(decision.decision_id, other_decision.decision_id)
        self.assertTrue(self.repo.save(decision))
        self.assertTrue(self.repo.save(other_decision))

    def test_Z_schema_v41_additive_and_idempotent(self) -> None:
        migrate(self.connection)  # idempotent re-run
        self.assertEqual(SCHEMA_VERSION, 41)
        tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("research_evidence_mutation_decisions", tables)
        # Additive: every prior hotfix's table still exists.
        for prior_table in ("research_hypothesis_proposals", "research_direction_evidence", "research_directions"):
            self.assertIn(prior_table, tables)


class RegressionTests(unittest.TestCase):
    def test_AA_169a_release_check_unchanged(self) -> None:
        payload = production_bounded_hypothesis_proposal_release_check()
        self.assertEqual(payload["safety"], "pass")

    def test_AB_169b_release_check_unchanged(self) -> None:
        payload = production_candidate_independent_evidence_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertEqual(payload["schema_version"], 41)

    def test_AC_170_sqlite_lock_stability_unchanged(self) -> None:
        payload = production_sqlite_lock_stability_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertEqual(payload["schema_version"], 41)

    def test_AD_no_autonomous_scheduler_wiring(self) -> None:
        source = inspect.getsource(evidence_mutation_policy)
        scheduler_module_name = "autonomous" + "_research_runtime"
        self.assertNotIn(scheduler_module_name, source)


class ReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes(self) -> None:
        payload = production_evidence_mutation_policy_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertEqual(payload["schema_version"], 41)
        self.assertFalse(payload["candidate_created"])
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["parameter_value_selected"])
        self.assertFalse(payload["backtest_executed"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])
        self.assertFalse(payload["production_applied"])
        self.assertFalse(payload["scheduler_wired"])

    def test_policy_version_constant(self) -> None:
        self.assertEqual(EVIDENCE_MUTATION_POLICY_VERSION, 1)

    def test_mutation_concept_taxonomy_is_conservative(self) -> None:
        self.assertEqual(len(MutationConcept), 1)
        self.assertEqual(list(FAILURE_CLASS_MUTATION_CONCEPT.keys()), [FailureClass.COST_SLIPPAGE_FRAGILITY])


if __name__ == "__main__":
    unittest.main()
