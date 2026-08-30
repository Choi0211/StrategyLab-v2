from __future__ import annotations

import unittest
from dataclasses import replace

from gaon.knowledge.research_mission import add_candidate, candidate_records, extract_or_update_mission, record_blocked
from gaon.knowledge.strategy_candidate import StrategyCandidateStatus, new_candidate
from gaon.research.bounded_hypothesis_generation import generate_bounded_hypothesis
from gaon.research.direction_evidence import RequirementSatisfactionState
from gaon.research.evidence_mutation_policy import _fixture_direction_and_analysis, _fixture_evidence, evaluate_evidence_mutation_policy
from gaon.research.hypothesis_proposal import ProposalStatus
from gaon.research.proposal_candidate_bridge import advance_mission_with_candidate, create_candidate_from_proposal

NOW = "2026-08-30T00:00:00Z"


def _seeded_mission_and_proposal():
    mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요", existing=None, now=NOW)
    parent = new_candidate("breakout_standard", sequence=1, now=NOW)
    parent = replace(
        parent, status=StrategyCandidateStatus.STAGNANT,
        rejected_reason="stagnation: no measurable progress across bounded cycles",
        validation_stage_status={"transaction_cost_stress": "fail_underperformed_baseline"},
    )
    mission = add_candidate(mission, parent, now=NOW)
    mission = record_blocked(mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=NOW)

    direction, analysis = _fixture_direction_and_analysis(NOW)
    analysis = replace(analysis, evidence_candidate_ids=(parent.candidate_id,))
    evidence = _fixture_evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1, now=NOW)
    decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
    proposals = generate_bounded_hypothesis(decision, direction, analysis, (parent,), now=NOW)
    ready = next(p for p in proposals if p.status is ProposalStatus.READY_FOR_EVIDENCE)
    return mission, parent, ready


class CandidateCreationTests(unittest.TestCase):
    def test_A_valid_persisted_proposal_creates_candidate(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        self.assertIsNotNone(result)
        new_mission, candidate = result
        self.assertIn(candidate.candidate_id, [c.candidate_id for c in candidate_records(new_mission)])

    def test_B_malformed_proposal_does_not_create_candidate(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        malformed = proposal.__class__(**{**proposal.__dict__, "status": ProposalStatus.REJECTED})
        candidate = create_candidate_from_proposal(malformed, (parent,), mission_candidate_sequence=2, now=NOW)
        self.assertIsNone(candidate)

    def test_B2_proposal_with_no_parent_in_history_does_not_create_candidate(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        candidate = create_candidate_from_proposal(proposal, (), mission_candidate_sequence=2, now=NOW)
        self.assertIsNone(candidate)

    def test_C_exactly_one_authorized_field_changes(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        _, candidate = result
        mutation = proposal.mutations[0]
        parent_dict = dict(parent.spec_rules[mutation.dict_name])
        child_dict = dict(candidate.spec_rules[mutation.dict_name])
        self.assertNotEqual(parent_dict[mutation.field], child_dict[mutation.field])

    def test_D_all_other_canonical_fields_unchanged(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        _, candidate = result
        mutation = proposal.mutations[0]
        for dict_name in ("entry", "exit", "filters"):
            parent_dict = dict(parent.spec_rules.get(dict_name) or {})
            child_dict = dict(candidate.spec_rules.get(dict_name) or {})
            for key in set(parent_dict) | set(child_dict):
                if dict_name == mutation.dict_name and key == mutation.field:
                    continue
                self.assertEqual(parent_dict.get(key), child_dict.get(key), f"{dict_name}.{key} unexpectedly changed")

    def test_E_no_production_strategy_import(self) -> None:
        import inspect

        import gaon.research.proposal_candidate_bridge as module

        source = inspect.getsource(module)
        for forbidden in ("gaon.adapters.trading", "gaon.adapters.strategy_execution", "gaon.adapters.strategy_deployment", "gaon.knowledge.promotion_gate", "gaon.knowledge.human_gated_promotion"):
            self.assertNotIn(f"import {forbidden}", source)
            self.assertNotIn(f"from {forbidden}", source)

    def test_F_candidate_enters_exploring_status_for_existing_validation_stack(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        _, candidate = result
        self.assertEqual(candidate.status, StrategyCandidateStatus.EXPLORING)

    def test_G_fingerprint_matches_proposal_novelty_fingerprint(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        _, candidate = result
        self.assertEqual(candidate.strategy_fingerprint, proposal.novelty_fingerprint)

    def test_H_missing_provider_data_does_not_become_success(self) -> None:
        # A blocked policy decision never even reaches generate_bounded_hypothesis
        # with a READY_FOR_EVIDENCE proposal (see test_bounded_hypothesis_
        # generation.py's own K/rejection tests) - so this bridge is never
        # called with fabricated success; a None proposal is a safe no-op.
        mission, parent, _ = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, None, now=NOW)
        self.assertIsNone(result)

    def test_I_rejected_candidate_allows_another_bounded_proposal_if_budget_remains(self) -> None:
        # The new candidate's own terminal state reshapes the mission's
        # history fingerprint (mission_history_fingerprint includes every
        # terminal candidate) - a fresh, distinct ResearchDirection/
        # evidence/policy/proposal chain is what "another bounded proposal"
        # means here, never a second mutation from the SAME unchanged
        # direction (see docs/architecture/Hotfix169DEF*.md, Known
        # Limitations, for why generate_bounded_proposals's own parent-
        # selection makes a same-direction second proposal a DUPLICATE by
        # design).
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        new_mission, candidate = result
        rejected_candidate = replace(candidate, status=StrategyCandidateStatus.REJECTED, rejected_reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols")
        from gaon.knowledge.research_mission import update_candidate

        mission_with_rejection = update_candidate(new_mission, rejected_candidate, now=NOW)
        from gaon.research.research_direction import analyze_mission_failure

        original_fingerprint = analyze_mission_failure(new_mission, session_ref="s", now=NOW).fingerprint
        new_fingerprint = analyze_mission_failure(mission_with_rejection, session_ref="s", now=NOW).fingerprint
        self.assertNotEqual(original_fingerprint, new_fingerprint)

    def test_J_idempotent_second_call_on_updated_mission_is_noop(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        new_mission, _ = result
        second = advance_mission_with_candidate(new_mission, proposal, now=NOW)
        self.assertIsNone(second)

    def test_K_no_champion_promotion_field_set(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        _, candidate = result
        self.assertIsNone(candidate.promotion_ready_at)

    def test_L_no_approval_field_bypassed(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        new_mission, _ = result
        from gaon.knowledge.research_mission import MissionStatus

        self.assertEqual(new_mission.status, MissionStatus.ACTIVE)
        self.assertNotEqual(new_mission.status, MissionStatus.AWAITING_HUMAN_APPROVAL)

    def test_M_no_apply_deploy_field_exists_on_candidate(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        _, candidate = result
        self.assertFalse(hasattr(candidate, "applied_at"))
        self.assertFalse(hasattr(candidate, "deployed_at"))

    def test_N_no_order_field_exists_on_candidate(self) -> None:
        mission, parent, proposal = _seeded_mission_and_proposal()
        result = advance_mission_with_candidate(mission, proposal, now=NOW)
        _, candidate = result
        self.assertFalse(hasattr(candidate, "order_id"))


class ReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes(self) -> None:
        from gaon.research.proposal_candidate_bridge import production_autonomous_candidate_validation_release_check

        payload = production_autonomous_candidate_validation_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertFalse(payload["champion_auto_promoted"])
        self.assertFalse(payload["approval_bypassed"])
        self.assertFalse(payload["production_applied"])
        self.assertFalse(payload["order_executed"])


if __name__ == "__main__":
    unittest.main()
