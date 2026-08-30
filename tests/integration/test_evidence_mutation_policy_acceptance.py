"""Hotfix #169C acceptance test: FailureAnalysis -> ResearchDirection ->
DirectionEvidenceAcquisition (#169B) -> EvidenceMutationPolicyDecision,
exercised end to end for the exact production-shaped
``cost_slippage_fragility`` / PARTIAL-evidence case.

Core acceptance criterion this proves: real (structured, not raw-text)
PARTIAL academic evidence with a non-zero source count makes
``REDUCE_ENTRY_FREQUENCY`` eligible for bounded RESEARCH on
``breakout_lookback`` (INCREASE_ONLY) - while ``channel_exit_lookback``
stays rejected for this mapping, ``protective_stop_pct`` stays
REVIEW_REQUIRED, and no numeric value, proposal, candidate, backtest,
order, or apply is ever produced.
"""

from __future__ import annotations

import sqlite3
import unittest

from gaon.research.direction_evidence import DirectionEvidenceAcquisition, EvidenceRequirementKind, RequirementResult, RequirementSatisfactionState
from gaon.research.evidence_mutation_policy import (
    EvidenceMutationPolicyRepository,
    MutationConcept,
    MutationDimensionPolicy,
    MutationDirection,
    PolicyStatus,
    evaluate_evidence_mutation_policy,
)
from gaon.research.research_direction import (
    FailureAnalysis,
    FailureClass,
    NextResearchAction,
    ResearchDirection,
    ResearchDirectionStatus,
)
from gaon.runtime.migrations import migrate

NOW = "2026-08-30T00:00:00Z"


def _cost_slippage_direction() -> tuple[ResearchDirection, FailureAnalysis]:
    session_ref = "acceptance-169c-session"
    mission_id = "acceptance-169c-mission"
    fingerprint = "acceptance-169c-cost-slippage-fingerprint"
    analysis = FailureAnalysis(
        analysis_id=f"failure-analysis:{fingerprint}",
        session_ref=session_ref,
        mission_id=mission_id,
        blocked_reason="cost/slippage fragility acceptance fixture",
        breakdown={FailureClass.COST_SLIPPAGE_FRAGILITY.value: 3},
        dominant_failure_class=FailureClass.COST_SLIPPAGE_FRAGILITY,
        evidence_candidate_ids=("candidate-a", "candidate-b", "candidate-c"),
        fingerprint=fingerprint,
        created_at=NOW,
    )
    direction = ResearchDirection(
        direction_id=f"research-direction:{fingerprint}",
        session_ref=session_ref,
        mission_id=mission_id,
        source_blocker=analysis.blocked_reason,
        failure_analysis_id=analysis.analysis_id,
        priority={"tier": "medium"},
        rationale="Acceptance-test direction for evidence mutation policy.",
        evidence_requirements=(
            "transaction-cost/slippage sensitivity evidence, and confirmation the cost model matches live execution",
        ),
        allowed_research_scope=("external_academic_research",),
        prohibited_actions=("strategy_mutation", "candidate_creation", "backtest_execution", "order_execution"),
        next_research_action=NextResearchAction.INVESTIGATE_COST_FRAGILITY,
        status=ResearchDirectionStatus.AWAITING_EVIDENCE,
        fingerprint=fingerprint,
        created_at=NOW,
        updated_at=NOW,
    )
    return direction, analysis


def _partial_direction_evidence(direction: ResearchDirection, analysis: FailureAnalysis) -> DirectionEvidenceAcquisition:
    fingerprint = "acceptance-169c-evidence-fingerprint"
    return DirectionEvidenceAcquisition(
        evidence_acquisition_id=f"direction-evidence:{fingerprint}",
        session_ref=direction.session_ref,
        mission_id=direction.mission_id,
        research_direction_id=direction.direction_id,
        failure_analysis_id=analysis.analysis_id,
        failure_class=analysis.dominant_failure_class,
        research_question_id="research-question:acceptance-169c",
        query_fingerprint=fingerprint,
        requirement_results=(
            RequirementResult(
                component_id="transaction_cost_slippage_sensitivity",
                kind=EvidenceRequirementKind.ACADEMIC_EXTERNAL,
                state=RequirementSatisfactionState.PARTIAL,
                evidence_source_count=1,
                blockers=(),
                executor_terminal_state="unresolved_conflict",
            ),
            RequirementResult(
                component_id="cost_model_matches_live_execution",
                kind=EvidenceRequirementKind.OPERATIONAL_LIVE_EXECUTION,
                state=RequirementSatisfactionState.REQUIRES_OPERATIONAL_EVIDENCE,
                evidence_source_count=0,
                blockers=("operational_evidence_requires_live_candidate",),
                executor_terminal_state=None,
            ),
        ),
        overall_state=__import__("gaon.research.direction_evidence", fromlist=["OverallAcquisitionState"]).OverallAcquisitionState.PARTIAL,
        fingerprint=fingerprint,
        created_at=NOW,
        updated_at=NOW,
    )


class CostSlippagePartialEvidenceAcceptanceTests(unittest.TestCase):
    def test_partial_evidence_yields_research_only_eligible_decision(self) -> None:
        direction, analysis = _cost_slippage_direction()
        evidence = _partial_direction_evidence(direction, analysis)

        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)

        self.assertEqual(decision.policy_status, PolicyStatus.ELIGIBLE_FOR_HYPOTHESIS_RESEARCH)
        self.assertEqual(decision.mutation_concepts, (MutationConcept.REDUCE_ENTRY_FREQUENCY,))
        self.assertEqual(decision.allowed_dimensions, ("breakout_lookback",))
        self.assertEqual(
            decision.allowed_dimension_policies,
            (MutationDimensionPolicy(dimension="breakout_lookback", allowed_operation=MutationDirection.INCREASE_ONLY),),
        )
        self.assertIn("protective_stop_pct", decision.review_required_dimensions)
        self.assertIn("channel_exit_lookback", decision.forbidden_dimensions)

        # Lineage is fully preserved back to the failure analysis / direction / evidence acquisition.
        self.assertEqual(decision.session_ref, direction.session_ref)
        self.assertEqual(decision.mission_id, direction.mission_id)
        self.assertEqual(decision.research_direction_id, direction.direction_id)
        self.assertEqual(decision.evidence_acquisition_id, evidence.evidence_acquisition_id)
        self.assertEqual(decision.failure_analysis_id, analysis.analysis_id)
        self.assertEqual(decision.failure_class, FailureClass.COST_SLIPPAGE_FRAGILITY)

        # No numeric value, proposal, candidate, backtest, order, or apply -
        # structurally absent from the decision object itself.
        self.assertFalse(hasattr(decision, "proposed_value"))
        self.assertFalse(hasattr(decision, "candidate_id"))
        self.assertFalse(hasattr(decision, "backtest_result"))
        self.assertFalse(hasattr(decision, "order_id"))

    def test_operational_requirement_never_hidden_by_eligible_status(self) -> None:
        direction, analysis = _cost_slippage_direction()
        evidence = _partial_direction_evidence(direction, analysis)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)
        operational = decision.evidence_state["components"]["cost_model_matches_live_execution"]
        self.assertEqual(operational["state"], RequirementSatisfactionState.REQUIRES_OPERATIONAL_EVIDENCE.value)

    def test_decision_persists_and_is_reloadable_via_a_fresh_repository(self) -> None:
        direction, analysis = _cost_slippage_direction()
        evidence = _partial_direction_evidence(direction, analysis)
        decision = evaluate_evidence_mutation_policy(direction, analysis, evidence, now=NOW)

        connection = sqlite3.connect(":memory:")
        try:
            migrate(connection)
            EvidenceMutationPolicyRepository(connection).save(decision)
            reloaded = EvidenceMutationPolicyRepository(connection).find_by_fingerprint(decision.session_ref, decision.fingerprint)
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.policy_status, PolicyStatus.ELIGIBLE_FOR_HYPOTHESIS_RESEARCH)
            self.assertEqual(reloaded.allowed_dimensions, ("breakout_lookback",))
            self.assertEqual(reloaded.research_direction_id, direction.direction_id)
        finally:
            connection.close()

    def test_provider_unavailable_still_blocked_never_falls_back_to_failure_class_alone(self) -> None:
        direction, analysis = _cost_slippage_direction()
        decision = evaluate_evidence_mutation_policy(direction, analysis, None, now=NOW)
        self.assertEqual(decision.policy_status, PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE)
        self.assertEqual(decision.allowed_dimensions, ())


if __name__ == "__main__":
    unittest.main()
