"""Hotfix #169B acceptance test: ResearchDirection -> ResearchQuestion ->
existing production AutonomousExternalResearchExecutor -> durable
direction-level evidence, exercised end to end for the real production
``cost_slippage_fragility`` direction shape (the only failure class #168/
#169A actually produce today).

Core acceptance criterion this proves: regardless of whether the external
academic provider is reachable, the overall acquisition state for
``cost_slippage_fragility`` is NEVER a bare ``ACQUIRED`` - because
"confirmation the cost model matches live execution" structurally cannot be
satisfied before a candidate exists, and always resolves to
``REQUIRES_OPERATIONAL_EVIDENCE`` honestly.
"""

from __future__ import annotations

import sqlite3
import unittest

from gaon.knowledge.content_acquisition import ContentAcquisitionPolicy, FetchPayload
from gaon.knowledge.execution import NetworkExecutionPolicy
from gaon.knowledge.external_research_execution import ContentResolutionPayload
from gaon.research.direction_evidence import (
    DirectionEvidenceRepository,
    EvidenceRequirementKind,
    OverallAcquisitionState,
    RequirementSatisfactionState,
    acquire_direction_evidence,
    build_production_executor,
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

_PASSING_CROSSREF_ITEM = {
    "DOI": "10.9999/acceptance-fixture",
    "type": "journal-article",
    "title": ["Transaction Cost and Slippage Sensitivity in Systematic Trading"],
    "publisher": "Acceptance Fixture Press",
    "container-title": ["Journal of Acceptance Fixtures"],
    "abstract": (
        "This paper studies transaction cost sensitivity and slippage impact "
        "on systematic trading strategy robustness across turnover regimes."
    ),
    "subject": ["finance"],
    "URL": "https://doi.org/10.9999/acceptance-fixture",
}


class _CrossrefTransport:
    def __init__(self, items: tuple[dict, ...]) -> None:
        self._items = items

    def get_json(self, url: str, *, policy: NetworkExecutionPolicy):
        return {"message": {"items": list(self._items)}}


class _DoiResolutionTransport:
    def resolve(self, url: str, *, policy: ContentAcquisitionPolicy):
        return ContentResolutionPayload(final_url="https://arxiv.org/abs/acceptance-fixture", redirect_chain=(url,))


class _ContentTransport:
    def fetch(self, target, *, policy: ContentAcquisitionPolicy):
        return FetchPayload(
            final_url=target.source_locator,
            content_type="text/plain",
            content=b"transaction cost slippage sensitivity acceptance fixture content",
        )


def _cost_slippage_direction() -> tuple[ResearchDirection, FailureAnalysis]:
    session_ref = "acceptance-session"
    mission_id = "acceptance-mission"
    fingerprint = "acceptance-cost-slippage-fingerprint"
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
        rationale="Acceptance-test direction for candidate-independent evidence acquisition.",
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


class CostSlippageFragilityAcceptanceTests(unittest.TestCase):
    def test_evidence_available_never_yields_full_acquired(self) -> None:
        direction, analysis = _cost_slippage_direction()
        executor = build_production_executor(
            discovery_transport=_CrossrefTransport((_PASSING_CROSSREF_ITEM,)),
            doi_resolution_transport=_DoiResolutionTransport(),
            content_transport=_ContentTransport(),
        )
        result = acquire_direction_evidence(direction, analysis, executor=executor, now=NOW)

        academic = next(r for r in result.requirement_results if r.kind is EvidenceRequirementKind.ACADEMIC_EXTERNAL)
        operational = next(r for r in result.requirement_results if r.kind is EvidenceRequirementKind.OPERATIONAL_LIVE_EXECUTION)

        # Requirement 1: real evidence was genuinely found and acquired
        # (never a fabricated/zero-source "success").
        self.assertGreater(academic.evidence_source_count, 0)
        self.assertIn(
            academic.state,
            (RequirementSatisfactionState.ACQUIRED, RequirementSatisfactionState.PARTIAL),
        )

        # Requirement 2: the operational/live-execution requirement is
        # NEVER satisfied via external/academic evidence, regardless of
        # how well requirement 1 did.
        self.assertEqual(operational.state, RequirementSatisfactionState.REQUIRES_OPERATIONAL_EVIDENCE)
        self.assertEqual(operational.evidence_source_count, 0)

        # Overall: never a bare ACQUIRED for this failure class.
        self.assertNotEqual(result.overall_state, OverallAcquisitionState.ACQUIRED)
        self.assertEqual(result.overall_state, OverallAcquisitionState.PARTIAL)

    def test_provider_unavailable_is_honest_and_still_never_acquired(self) -> None:
        direction, analysis = _cost_slippage_direction()
        result = acquire_direction_evidence(direction, analysis, executor=None, now=NOW)

        academic = next(r for r in result.requirement_results if r.kind is EvidenceRequirementKind.ACADEMIC_EXTERNAL)
        operational = next(r for r in result.requirement_results if r.kind is EvidenceRequirementKind.OPERATIONAL_LIVE_EXECUTION)

        self.assertEqual(academic.state, RequirementSatisfactionState.PROVIDER_NOT_CONFIGURED)
        self.assertEqual(operational.state, RequirementSatisfactionState.REQUIRES_OPERATIONAL_EVIDENCE)
        self.assertNotEqual(result.overall_state, OverallAcquisitionState.ACQUIRED)
        self.assertIn(result.overall_state, (OverallAcquisitionState.PARTIAL, OverallAcquisitionState.UNMET))

    def test_zero_academic_results_is_honest_and_still_never_acquired(self) -> None:
        direction, analysis = _cost_slippage_direction()
        executor = build_production_executor(discovery_transport=_CrossrefTransport(()))
        result = acquire_direction_evidence(direction, analysis, executor=executor, now=NOW)

        academic = next(r for r in result.requirement_results if r.kind is EvidenceRequirementKind.ACADEMIC_EXTERNAL)
        self.assertEqual(academic.state, RequirementSatisfactionState.UNMET_REQUIREMENT)
        self.assertNotEqual(result.overall_state, OverallAcquisitionState.ACQUIRED)

    def test_durable_persistence_survives_a_fresh_repository_instance(self) -> None:
        direction, analysis = _cost_slippage_direction()
        executor = build_production_executor(
            discovery_transport=_CrossrefTransport((_PASSING_CROSSREF_ITEM,)),
            doi_resolution_transport=_DoiResolutionTransport(),
            content_transport=_ContentTransport(),
        )
        result = acquire_direction_evidence(direction, analysis, executor=executor, now=NOW)

        connection = sqlite3.connect(":memory:")
        try:
            migrate(connection)
            DirectionEvidenceRepository(connection).save(result)
            # A brand-new repository object over the same connection must
            # see the same durable row - this is real SQLite persistence,
            # not an in-process cache.
            reloaded = DirectionEvidenceRepository(connection).find_by_fingerprint(result.session_ref, result.fingerprint)
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.overall_state, OverallAcquisitionState.PARTIAL)
            self.assertEqual(reloaded.research_direction_id, direction.direction_id)
            self.assertEqual(reloaded.mission_id, direction.mission_id)
            self.assertEqual(reloaded.failure_analysis_id, analysis.analysis_id)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
