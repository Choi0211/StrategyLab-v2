"""Gaon Agent Foundation V2.

Typed foundations for the next-generation Gaon architecture (PR #214). This
package deliberately contains *no* provider, network, shell, git or
production access - it is the honest, single-source-of-truth description of
what Gaon can and cannot do, plus the thin conversational routing seam that
lets genuine conversation reach the LLM instead of a canned fallback.

See ``docs/architecture/GaonAgentFoundationV2.md`` for the design and
``docs/architecture/GaonAgentRoadmapV2.md`` for the #214 -> #219 roadmap.
"""

from __future__ import annotations

from gaon.runtime.gaon_agent.capabilities import (
    Capability,
    CapabilityRegistry,
    CapabilityState,
    CapabilityUnavailableError,
    SafetyClass,
    capability_prompt_summary,
    default_capability_registry,
)
from gaon.runtime.gaon_agent.developer_boundary import (
    DEVELOPER_AGENT_CAPABILITIES,
    FORBIDDEN_IN_AGENT_LAYER,
    assert_not_privileged,
)
from gaon.runtime.gaon_agent.gap_analysis import (
    GapAnalysisResult,
    GapNeed,
    diagnose_gap,
    is_gap_fill_request,
)
from gaon.runtime.gaon_agent.evidence import (
    Claim,
    EvidenceIngestor,
    EvidenceRecord,
    NullEvidenceIngestor,
    Observation,
    SourceRef,
    VerificationState,
)
from gaon.runtime.gaon_agent.multi_intent import TurnSegment, recompose_answers, segment_turn
from gaon.runtime.gaon_agent.multimodal import (
    Modality,
    MultimodalReference,
    describe_multimodal_request,
)
from gaon.runtime.gaon_agent.needs import (
    Blocker,
    BlockerKind,
    NeedAssessment,
    RequestedGoal,
    assess_from_registry,
    diagnose,
)
from gaon.runtime.gaon_agent.research_preferences import (
    ResearchPreferences,
    extract_research_preferences,
    mentions_research_preferences,
    reconcile_with_mission,
    render_research_preferences_summary,
)
from gaon.runtime.gaon_agent.runtime_status import (
    CapabilityRuntimeObservation,
    ProviderRuntimeMonitor,
    RuntimeAvailability,
    RuntimeObservationSource,
    RuntimeReason,
    general_conversation_runtime,
    is_connectivity_error,
    observation_index,
    resolve_runtime_observations,
    runtime_capability_note,
)
from gaon.runtime.gaon_agent.turn_router import (
    GaonTurnRouter,
    RoutedTurn,
    TurnLane,
)

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "CapabilityState",
    "CapabilityUnavailableError",
    "SafetyClass",
    "capability_prompt_summary",
    "default_capability_registry",
    "DEVELOPER_AGENT_CAPABILITIES",
    "FORBIDDEN_IN_AGENT_LAYER",
    "assert_not_privileged",
    "Claim",
    "EvidenceIngestor",
    "EvidenceRecord",
    "NullEvidenceIngestor",
    "Observation",
    "SourceRef",
    "VerificationState",
    "TurnSegment",
    "recompose_answers",
    "segment_turn",
    "Modality",
    "MultimodalReference",
    "describe_multimodal_request",
    "NeedAssessment",
    "RequestedGoal",
    "assess_from_registry",
    "Blocker",
    "BlockerKind",
    "diagnose",
    "GapAnalysisResult",
    "GapNeed",
    "diagnose_gap",
    "is_gap_fill_request",
    "ResearchPreferences",
    "extract_research_preferences",
    "mentions_research_preferences",
    "reconcile_with_mission",
    "render_research_preferences_summary",
    "CapabilityRuntimeObservation",
    "ProviderRuntimeMonitor",
    "RuntimeAvailability",
    "RuntimeObservationSource",
    "RuntimeReason",
    "general_conversation_runtime",
    "is_connectivity_error",
    "observation_index",
    "resolve_runtime_observations",
    "runtime_capability_note",
    "GaonTurnRouter",
    "RoutedTurn",
    "TurnLane",
]
