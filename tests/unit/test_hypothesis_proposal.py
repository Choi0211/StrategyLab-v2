from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace

from gaon.knowledge.research_mission import add_candidate, candidate_records, extract_or_update_mission, record_blocked
from gaon.knowledge.strategy_candidate import ALL_STRATEGY_FAMILY_TEMPLATES, StrategyCandidateStatus, new_candidate
from gaon.research.hypothesis_proposal import (
    CANONICAL_MUTATION_POLICY,
    FAILURE_CLASS_MUTATION_SUPPORT,
    PROHIBITED_DIMENSION_NAMES,
    BoundedHypothesisProposalRepository,
    MutationAutonomyClass,
    MutationBudget,
    MutationMethod,
    ProposalStatus,
    generate_bounded_proposals,
)
from gaon.research.research_direction import FailureClass, analyze_mission_failure, plan_research_direction
from gaon.research.research_priority import propose_research_priority
from gaon.runtime.migrations import SCHEMA_VERSION, migrate

_NOW = "2026-08-30T00:00:00Z"
_SESSION_REF = "telegram:100"
_DEFAULT_STAGNANT_REASON = "stagnation: no measurable progress across bounded cycles"


def _mission():
    return extract_or_update_mission(
        "국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요", existing=None, now=_NOW
    )


def _production_shaped_exhausted_mission():
    """Reproduces the exact real production breakdown reported for #168:
    9 terminal candidates, cost_slippage_fragility=4 (dominant),
    regime_sensitivity=2, robustness_failure=2, economic_viability_failure=1."""
    mission = _mission()
    specs = (
        ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
        ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
        ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
        ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
        ({"regime_validation": "fail"}, StrategyCandidateStatus.STAGNANT),
        ({"regime_validation": "fail"}, StrategyCandidateStatus.STAGNANT),
        ({"out_of_sample": "fail"}, StrategyCandidateStatus.STAGNANT),
        ({"out_of_sample": "fail"}, StrategyCandidateStatus.STAGNANT),
        (None, StrategyCandidateStatus.REJECTED),
    )
    for sequence, (family, (stage_status, status)) in enumerate(
        zip((t.family for t in ALL_STRATEGY_FAMILY_TEMPLATES), specs), start=1
    ):
        candidate = new_candidate(family, sequence=sequence, now=_NOW)
        if stage_status is None:
            candidate = replace(
                candidate, status=status,
                rejected_reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols",
            )
        else:
            candidate = replace(candidate, status=status, rejected_reason=_DEFAULT_STAGNANT_REASON, validation_stage_status=stage_status)
        mission = add_candidate(mission, candidate, now=_NOW)
    mission = record_blocked(
        mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=_NOW
    )
    return mission


def _direction_and_analysis(mission):
    analysis = analyze_mission_failure(mission, session_ref=_SESSION_REF, now=_NOW)
    priority = propose_research_priority(mission, None)
    direction = plan_research_direction(analysis, priority, has_untried_family=False, has_recoverable_candidate=False, now=_NOW)
    return direction, analysis


class CanonicalMutationSurfaceTests(unittest.TestCase):
    def test_policy_is_exactly_the_six_real_canonical_fields(self) -> None:
        self.assertEqual(
            set(CANONICAL_MUTATION_POLICY.keys()),
            {"breakout_lookback", "channel_exit_lookback", "protective_stop_pct", "close_gt_ma20", "ma20_gt_ma60", "volume_gte_ma20"},
        )

    def test_no_prohibited_dimension_name_is_ever_a_policy_entry(self) -> None:
        for name in PROHIBITED_DIMENSION_NAMES:
            self.assertNotIn(name, CANONICAL_MUTATION_POLICY, f"{name} must never become a mutation dimension")

    def test_historical_domains_are_derived_from_the_real_templates_not_invented(self) -> None:
        self.assertEqual(CANONICAL_MUTATION_POLICY["breakout_lookback"].allowed_values, (10, 20, 30, 40))
        self.assertEqual(CANONICAL_MUTATION_POLICY["channel_exit_lookback"].allowed_values, (7, 10, 15, 20))
        self.assertEqual(sorted(CANONICAL_MUTATION_POLICY["protective_stop_pct"].allowed_values), [-8.0, -6.0, -5.0, -4.0])


class GenerateBoundedProposalsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mission = _production_shaped_exhausted_mission()
        self.direction, self.analysis = _direction_and_analysis(self.mission)
        self.candidate_history = candidate_records(self.mission)

    def test_A_structured_canonical_input_produces_bounded_proposals(self) -> None:
        self.assertEqual(self.analysis.dominant_failure_class, FailureClass.COST_SLIPPAGE_FRAGILITY)
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        self.assertTrue(all(p.status == ProposalStatus.READY_FOR_EVIDENCE for p in proposals))
        self.assertGreaterEqual(len(proposals), 1)
        for proposal in proposals:
            self.assertEqual(proposal.mutation_count, 1)
            self.assertEqual(len(proposal.mutations), 1)

    def test_B_no_llm_or_free_text_involved_values_come_only_from_policy_domain(self) -> None:
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        for proposal in proposals:
            mutation = proposal.mutations[0]
            domain = CANONICAL_MUTATION_POLICY[mutation.field].allowed_values
            self.assertIn(mutation.proposed_value, domain, "proposed value must come from the deterministic historical domain, never free text/LLM output")

    def test_C_mutation_budget_respected_per_proposal_and_per_direction(self) -> None:
        budget = MutationBudget(max_dimensions_changed_per_proposal=1, max_proposals_per_direction=1)
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, budget=budget, now=_NOW)
        self.assertLessEqual(len(proposals), 1)
        for proposal in proposals:
            self.assertLessEqual(proposal.mutation_count, 1)

    def test_D_field_not_in_allowlist_is_never_generated(self) -> None:
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        for proposal in proposals:
            self.assertIn(proposal.mutations[0].field, CANONICAL_MUTATION_POLICY)

    def test_D2_forbidden_dimension_is_never_produced_even_if_upstream_policy_config_is_misconfigured(self) -> None:
        # Defense-in-depth: even if a future caller mistakenly points a
        # failure-class mapping at a forbidden/non-existent dimension, the
        # generator must never manufacture a mutation for it.
        malicious_support = {FailureClass.COST_SLIPPAGE_FRAGILITY: ("leverage", "position_size", "breakout_lookback")}
        proposals = generate_bounded_proposals(
            self.direction, self.analysis, self.candidate_history, failure_class_support=malicious_support, now=_NOW
        )
        fields_generated = {mutation.field for proposal in proposals for mutation in proposal.mutations}
        self.assertNotIn("leverage", fields_generated)
        self.assertNotIn("position_size", fields_generated)

    def test_E_out_of_bounds_value_never_generated(self) -> None:
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        for proposal in proposals:
            mutation = proposal.mutations[0]
            self.assertIn(mutation.proposed_value, CANONICAL_MUTATION_POLICY[mutation.field].allowed_values)

    def test_F_no_random_or_arbitrary_value_generation_deterministic_across_calls(self) -> None:
        first = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        second = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        self.assertEqual(
            [(p.proposal_id, p.novelty_fingerprint) for p in first],
            [(p.proposal_id, p.novelty_fingerprint) for p in second],
            "identical input must always produce identical output - no randomness anywhere in generation",
        )

    def test_G_identical_canonical_proposal_is_deduped_on_regeneration(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            migrate(connection)
            repository = BoundedHypothesisProposalRepository(connection)
            first = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
            for proposal in first:
                repository.put(proposal)
            existing_fps = repository.existing_fingerprints_for_session(_SESSION_REF)
            second = generate_bounded_proposals(
                self.direction, self.analysis, self.candidate_history, existing_proposal_fingerprints=existing_fps, now=_NOW
            )
            self.assertTrue(all(p.status == ProposalStatus.DUPLICATE for p in second))
            for proposal in second:
                self.assertFalse(repository.put(proposal), "regenerating an identical proposal must never insert a new row")
            self.assertEqual(repository.count_for_direction(self.direction.direction_id), len(first))
        finally:
            connection.close()

    def test_H_mutation_colliding_with_an_existing_terminal_candidate_is_rejected_as_duplicate(self) -> None:
        from gaon.research.multi_symbol import _strategy_from_candidate_spec

        # Force a real collision: craft a terminal candidate whose spec is
        # IDENTICAL to what breakout_lookback: 20->30 on the parent would
        # produce (same filters, only breakout_lookback differs from parent).
        parent = next(c for c in self.candidate_history if c.candidate_id == "KR-ST-001")
        collided_spec_rules = dict(parent.spec_rules)
        collided_spec_rules["entry"] = dict(collided_spec_rules["entry"])
        collided_spec_rules["entry"]["breakout_lookback"] = {"value": 30, "provenance": "research_candidate"}
        collided_fingerprint = _strategy_from_candidate_spec(collided_spec_rules, symbol="000000", created_at=_NOW).strategy_family_fingerprint

        colliding = new_candidate("breakout_slow_trend_confirmed", sequence=99, now=_NOW)
        colliding = replace(
            colliding,
            strategy_fingerprint=collided_fingerprint,
            spec_rules=collided_spec_rules,
            status=StrategyCandidateStatus.STAGNANT,
            rejected_reason=_DEFAULT_STAGNANT_REASON,
        )
        history_with_collision = (*self.candidate_history, colliding)

        proposals = generate_bounded_proposals(self.direction, self.analysis, history_with_collision, now=_NOW)
        lookback_proposal = next(p for p in proposals if p.mutations and p.mutations[0].field == "breakout_lookback")
        self.assertEqual(lookback_proposal.status, ProposalStatus.DUPLICATE)

    def test_I_unsupported_failure_class_returns_honest_unsupported(self) -> None:
        mission = _mission()
        candidate = new_candidate("breakout_standard", sequence=1, now=_NOW)
        candidate = replace(candidate, status=StrategyCandidateStatus.REJECTED, rejected_reason="some_future_reason_never_classified_here")
        mission = add_candidate(mission, candidate, now=_NOW)
        mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: x", now=_NOW)
        direction, analysis = _direction_and_analysis(mission)
        self.assertNotEqual(analysis.dominant_failure_class, FailureClass.COST_SLIPPAGE_FRAGILITY)

        proposals = generate_bounded_proposals(direction, analysis, candidate_records(mission), now=_NOW)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].status, ProposalStatus.UNSUPPORTED)
        self.assertEqual(proposals[0].mutations, ())

    def test_J_proposal_generation_never_mutates_mission_or_candidate_state(self) -> None:
        candidates_before = self.mission.candidates
        generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        self.assertEqual(self.mission.candidates, candidates_before, "generation must never mutate the ResearchMission (frozen dataclasses; this also guards against any accidental in-place logic)")

    def test_K_no_generated_mutation_ever_touches_a_forbidden_dimension(self) -> None:
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        for proposal in proposals:
            for mutation in proposal.mutations:
                self.assertNotIn(mutation.field, PROHIBITED_DIMENSION_NAMES)
            self.assertEqual(set(proposal.prohibited_dimensions), PROHIBITED_DIMENSION_NAMES)

    def test_N_lineage_is_traceable_mission_to_failure_analysis_to_direction_to_proposal(self) -> None:
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        for proposal in proposals:
            self.assertEqual(proposal.mission_id, self.mission.mission_id)
            self.assertEqual(proposal.source_failure_analysis_id, self.analysis.analysis_id)
            self.assertEqual(proposal.research_direction_id, self.direction.direction_id)
            self.assertIn(proposal.parent_candidate_ids[0], {c.candidate_id for c in self.candidate_history})

    def test_O_ready_for_evidence_is_not_ready_for_approval(self) -> None:
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        status_values = {p.status.value for p in proposals}
        self.assertNotIn("ready_for_approval", status_values)
        self.assertIn("ready_for_evidence", status_values)

    def test_economic_viability_and_robustness_failure_are_unsupported_not_fabricated(self) -> None:
        self.assertNotIn(FailureClass.ECONOMIC_VIABILITY_FAILURE, FAILURE_CLASS_MUTATION_SUPPORT)
        self.assertNotIn(FailureClass.ROBUSTNESS_FAILURE, FAILURE_CLASS_MUTATION_SUPPORT)
        self.assertNotIn(FailureClass.REGIME_SENSITIVITY, FAILURE_CLASS_MUTATION_SUPPORT)

    def test_bounds_exhaustion_is_honest_not_extrapolated(self) -> None:
        # breakout_lookback already at the historical maximum (40) - no
        # further HISTORICAL_NEIGHBOR_GRID value exists; must never invent one.
        mission = _mission()
        candidate = new_candidate("breakout_wide_standard", sequence=1, now=_NOW)  # lookback=40 (already max)
        candidate = replace(candidate, status=StrategyCandidateStatus.STAGNANT, rejected_reason=_DEFAULT_STAGNANT_REASON, validation_stage_status={"transaction_cost_stress": "fail_underperformed_baseline"})
        mission = add_candidate(mission, candidate, now=_NOW)
        mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: x", now=_NOW)
        direction, analysis = _direction_and_analysis(mission)
        self.assertEqual(analysis.dominant_failure_class, FailureClass.COST_SLIPPAGE_FRAGILITY)

        proposals = generate_bounded_proposals(direction, analysis, candidate_records(mission), now=_NOW)
        # The one allowed dimension for this failure class (breakout_lookback=40)
        # is already at its historical maximum - must resolve honestly, never invent one.
        self.assertTrue(all(p.status == ProposalStatus.UNSUPPORTED for p in proposals))


class PolicyHardeningTests(unittest.TestCase):
    """Hotfix #169A final policy audit hardening: channel_exit_lookback
    removed from the cost_slippage_fragility mapping (no code-grounded
    turnover mechanism), protective_stop_pct machine-gated as
    REVIEW_REQUIRED (a genuine per-trade risk parameter), boolean filters
    left unmapped (BOOLEAN_TOGGLE is direction-agnostic)."""

    def setUp(self) -> None:
        self.mission = _production_shaped_exhausted_mission()
        self.direction, self.analysis = _direction_and_analysis(self.mission)
        self.candidate_history = candidate_records(self.mission)

    def test_A_cost_slippage_fragility_still_produces_breakout_lookback_proposal(self) -> None:
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        fields = {mutation.field for p in proposals for mutation in p.mutations}
        self.assertIn("breakout_lookback", fields)

    def test_B_cost_slippage_fragility_never_produces_channel_exit_lookback_proposal(self) -> None:
        self.assertNotIn("channel_exit_lookback", FAILURE_CLASS_MUTATION_SUPPORT.get(FailureClass.COST_SLIPPAGE_FRAGILITY, ()))
        proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
        fields = {mutation.field for p in proposals for mutation in p.mutations}
        self.assertNotIn("channel_exit_lookback", fields)

    def test_C_protective_stop_pct_never_generated_even_if_failure_mapping_names_it(self) -> None:
        malicious_support = {FailureClass.COST_SLIPPAGE_FRAGILITY: ("protective_stop_pct", "breakout_lookback")}
        proposals = generate_bounded_proposals(
            self.direction, self.analysis, self.candidate_history, failure_class_support=malicious_support, now=_NOW
        )
        fields = {mutation.field for p in proposals for mutation in p.mutations}
        self.assertNotIn("protective_stop_pct", fields)
        # breakout_lookback (AUTONOMOUS_ALLOWED) in the same malicious mapping must still work normally.
        self.assertIn("breakout_lookback", fields)

    def test_C2_protective_stop_pct_alone_resolves_unsupported_not_silently_empty(self) -> None:
        only_stop_support = {FailureClass.COST_SLIPPAGE_FRAGILITY: ("protective_stop_pct",)}
        proposals = generate_bounded_proposals(
            self.direction, self.analysis, self.candidate_history, failure_class_support=only_stop_support, now=_NOW
        )
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].status, ProposalStatus.UNSUPPORTED)
        self.assertEqual(proposals[0].mutations, ())

    def test_D_protective_stop_pct_is_classified_review_required(self) -> None:
        self.assertEqual(CANONICAL_MUTATION_POLICY["protective_stop_pct"].autonomy_class, MutationAutonomyClass.REVIEW_REQUIRED)
        for field in ("breakout_lookback", "channel_exit_lookback", "close_gt_ma20", "ma20_gt_ma60", "volume_gte_ma20"):
            self.assertEqual(CANONICAL_MUTATION_POLICY[field].autonomy_class, MutationAutonomyClass.AUTONOMOUS_ALLOWED)

    def test_E_boolean_fields_not_activated_by_this_hardening(self) -> None:
        for failure_class, fields in FAILURE_CLASS_MUTATION_SUPPORT.items():
            for boolean_field in ("close_gt_ma20", "ma20_gt_ma60", "volume_gte_ma20"):
                self.assertNotIn(boolean_field, fields, f"{boolean_field} must not be wired to {failure_class} by this hardening pass")

    def test_F_arbitrary_forbidden_fields_still_blocked(self) -> None:
        malicious_support = {FailureClass.COST_SLIPPAGE_FRAGILITY: ("leverage", "position_size", "breakout_lookback")}
        proposals = generate_bounded_proposals(
            self.direction, self.analysis, self.candidate_history, failure_class_support=malicious_support, now=_NOW
        )
        fields = {mutation.field for p in proposals for mutation in p.mutations}
        self.assertNotIn("leverage", fields)
        self.assertNotIn("position_size", fields)

    def test_G_budget_dedup_lineage_durability_unchanged_by_hardening(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            migrate(connection)
            repository = BoundedHypothesisProposalRepository(connection)
            proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
            for proposal in proposals:
                self.assertLessEqual(proposal.mutation_count, MutationBudget().max_dimensions_changed_per_proposal)
                self.assertEqual(proposal.mission_id, self.mission.mission_id)
                self.assertEqual(proposal.research_direction_id, self.direction.direction_id)
                self.assertEqual(proposal.source_failure_analysis_id, self.analysis.analysis_id)
                repository.put(proposal)
            existing_fps = repository.existing_fingerprints_for_session(_SESSION_REF)
            regenerated = generate_bounded_proposals(
                self.direction, self.analysis, self.candidate_history, existing_proposal_fingerprints=existing_fps, now=_NOW
            )
            self.assertTrue(all(p.status == ProposalStatus.DUPLICATE for p in regenerated))
            reloaded = repository.list_for_direction(self.direction.direction_id)
            self.assertEqual(len(reloaded), len(proposals))
        finally:
            connection.close()

    def test_H_proposal_generation_leaves_all_safety_tables_untouched(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            migrate(connection)
            tables = (
                "champion_registry", "champion_history", "promotion_requests", "promotion_decisions",
                "approvals", "research_approval_decisions", "research_config_approvals",
                "strategy_deployment_requests", "strategy_deployment_runs",
                "strategy_execution_plans", "strategy_execution_runs",
            )

            def _counts():
                return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}

            before = _counts()
            candidates_before = len(self.mission.candidates)
            repository = BoundedHypothesisProposalRepository(connection)
            proposals = generate_bounded_proposals(self.direction, self.analysis, self.candidate_history, now=_NOW)
            for proposal in proposals:
                repository.put(proposal)
            after = _counts()

            self.assertEqual(before, after)
            self.assertEqual(len(self.mission.candidates), candidates_before)
        finally:
            connection.close()


class MigrationTests(unittest.TestCase):
    def test_schema_v39_is_additive_and_idempotent(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            migrate(connection)
            migrate(connection)  # idempotent re-run
            self.assertEqual(SCHEMA_VERSION, 42)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("research_hypothesis_proposals", tables)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_version WHERE version=42").fetchone()[0], 1)
        finally:
            connection.close()

    def test_proposal_durable_across_restart(self) -> None:
        import tempfile, os

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            mission = _production_shaped_exhausted_mission()
            direction, analysis = _direction_and_analysis(mission)
            history = candidate_records(mission)
            proposals = generate_bounded_proposals(direction, analysis, history, now=_NOW)

            connection = sqlite3.connect(path)
            migrate(connection)
            repository = BoundedHypothesisProposalRepository(connection)
            for proposal in proposals:
                repository.put(proposal)
            connection.close()

            restarted = sqlite3.connect(path)
            migrate(restarted)
            reloaded_repository = BoundedHypothesisProposalRepository(restarted)
            reloaded = reloaded_repository.list_for_direction(direction.direction_id)
            self.assertEqual(len(reloaded), len(proposals))
            restarted.close()
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
