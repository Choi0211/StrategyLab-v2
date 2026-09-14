"""Autonomous next-step selection for a durable ResearchMission BLOCKED on
``strategy_hypothesis_space_exhausted``, reached from a LIVE conversational
continuation turn (e.g. "단타 연구해주세요", "계속 연구해주세요", "부족한
부분을 채워주세요") - not the background autonomous-research tick.

Root cause this closes: a market-wide KR mission structurally BLOCKED
because the bounded declarative strategy-hypothesis grammar
(``gaon.knowledge.strategy_candidate``) is fully exhausted used to have its
live-conversation continuation short-circuit straight to
``research_mission.mission_blocked_message`` - an honest but static
explanation that never attempted the SAME bounded recovery/diagnosis
machinery ``gaon.runtime.autonomous_research_runtime.
AutonomousResearchRuntimeWorker`` already runs on its background tick
(Hotfix #168/#169). A user asking Gaon to continue got the same "you are
blocked" reply forever, with Gaon never autonomously trying the one safe
thing it could actually try, and never stating what it concretely
determined - the reply just implicitly left "what direction now?" for the
human to decide.

This module reuses - never duplicates - exactly two existing, already-
tested pieces of machinery, in order:

1. ``attempt_bounded_stagnation_recovery`` - bounded recovery that reopens a
   STAGNANT candidate that stalled purely on the progress-stall bookkeeping
   threshold (not a genuine dead end). When it succeeds, the mission is
   already ACTIVE again with a real candidate to continue validating -
   the caller resumes the EXISTING mission-driven research cycle
   (``LLMConversationBrain._try_mission_driven_research_cycle``) unchanged,
   so this is "execute the existing safe research continuation path", not a
   new one.
2. The Hotfix #168 FAILURE ANALYSIS -> RESEARCH PRIORITY -> RESEARCH
   DIRECTION planning stage (``analyze_mission_failure`` /
   ``propose_research_priority`` / ``plan_research_direction`` /
   ``ResearchDirectionRepository``) when recovery finds nothing - the exact
   same deterministic, read/plan/persist-only stage the background worker
   already runs, invoked here synchronously so a live turn gets an honest,
   evidence-grounded answer immediately instead of waiting for the next
   scheduled tick.

Deliberately NOT reused here: the Hotfix #169D-F evidence-acquisition /
policy / bounded-hypothesis-proposal / candidate-creation chain
(``AutonomousResearchRuntimeWorker._advance_evidence_mutation_chain``) -
that stage performs real external network evidence acquisition and is left
exclusively to the background worker's own bounded cadence; a live
conversational turn never triggers it. Nothing in this module ever mutates
strategy config, creates/promotes a candidate identity beyond the bounded
recovery above, creates an approval, or reaches any order/broker/champion-
promotion code path.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from gaon.knowledge.research_mission import (
    MissionStatus,
    ResearchMission,
    candidate_records,
    mission_status_block,
    render_blocked_reason_explanation,
)
from gaon.knowledge.strategy_candidate import next_untried_family
from gaon.research.research_direction import (
    FailureClass,
    ResearchDirectionRepository,
    analyze_mission_failure,
    plan_research_direction,
)
from gaon.research.research_priority import propose_research_priority

_STRUCTURAL_HYPOTHESIS_SPACE_EXHAUSTED = "strategy_hypothesis_space_exhausted"

# Parallel Korean phrasing for research_direction.FailureClass - kept
# separate from that module's own English breakdown/rationale fields (which
# other tests already assert on in English; this module never changes
# those) because this dict feeds a user-facing Korean conversational
# reply, never an internal/audit record.
_FAILURE_CLASS_LABEL_KO: dict[FailureClass, str] = {
    FailureClass.INSUFFICIENT_SAMPLE: "표본 부족",
    FailureClass.ECONOMIC_VIABILITY_FAILURE: "경제성(수익성) 검증 실패",
    FailureClass.COST_SLIPPAGE_FRAGILITY: "거래비용/슬리피지 민감도 미해결",
    FailureClass.REGIME_SENSITIVITY: "시장 국면(regime) 민감도",
    FailureClass.ROBUSTNESS_FAILURE: "강건성(robustness) 검증 실패",
    FailureClass.EVIDENCE_INSUFFICIENCY: "증거 표본 부족",
    FailureClass.DATA_PROVIDER_LIMITATION: "데이터 제공자 제한",
    FailureClass.VALIDATION_STAGNATION: "검증 정체",
    FailureClass.HYPOTHESIS_FAMILY_EXHAUSTION: "전략 가설군(bounded grammar) 소진",
    FailureClass.UNKNOWN: "미분류 사유",
}

_EVIDENCE_REQUIREMENT_KO: dict[FailureClass, str] = {
    FailureClass.INSUFFICIENT_SAMPLE: "이 미션이 아직 시도하지 않은 종목 범위에서의 독립적인 추가 증거",
    FailureClass.ECONOMIC_VIABILITY_FAILURE: (
        "양(+)의 수익 또는 과반 종목 수익성이 확인되는 추가 real 증거, 혹은 이 시장/전략군 조합이 "
        "근본적으로 적합하지 않다는 사람의 검토 결정"
    ),
    FailureClass.COST_SLIPPAGE_FRAGILITY: "거래비용/슬리피지 민감도 증거 및 비용 모델이 실제 체결과 일치하는지에 대한 확인",
    FailureClass.REGIME_SENSITIVITY: "추가적인 시장 국면/기간에 대한 증거",
    FailureClass.ROBUSTNESS_FAILURE: "아직 통과하지 못한 나머지 강건성 검증 축의 통과 결과",
    FailureClass.EVIDENCE_INSUFFICIENCY: "경제성 판단을 내리기 위한 더 큰 실제 거래/종목 표본",
    FailureClass.DATA_PROVIDER_LIMITATION: "막혀 있던 요청에 사용할 수 있는 데이터 제공자",
    FailureClass.VALIDATION_STAGNATION: "후보의 evidence revision을 바꿀 새로운 실질적 증거",
    FailureClass.HYPOTHESIS_FAMILY_EXHAUSTION: "사람/개발자가 검토한 bounded 전략 가설군 문법 확장",
    FailureClass.UNKNOWN: "미분류된 거부 사유에 대한 사람의 검토",
}


def is_structural_hypothesis_space_blocker(mission: ResearchMission) -> bool:
    """``True`` only for a mission BLOCKED with the specific structural
    ``strategy_hypothesis_space_exhausted`` reason - the same precise gate
    ``attempt_bounded_stagnation_recovery`` already uses. Every other
    BLOCKED reason (``selected_symbol_universe_exhausted``, a transient
    provider/data blocker, an unrecognized dynamic code) is untouched by
    this module and keeps its existing behavior."""
    return mission.status is MissionStatus.BLOCKED and (mission.blocked_reason or "").startswith(
        _STRUCTURAL_HYPOTHESIS_SPACE_EXHAUSTED
    )


@dataclass(frozen=True)
class StructuralBlockerContinuationOutcome:
    """Exactly one of the two fields is set, never both:

    - ``recovered_mission``: the mission is already reactivated (ACTIVE,
      with a real candidate re-selected for validation) - the caller
      resumes the existing mission-driven research cycle with it.
    - ``message``: no safe autonomous action exists; a concrete,
      capability-grounded (never fabricated) Korean explanation of what
      Gaon determined and what is genuinely still required.
    """

    recovered_mission: ResearchMission | None
    message: str | None


def _plan_and_render(mission: ResearchMission, *, session_id: str, now: str):
    """Shared FAILURE ANALYSIS -> RESEARCH PRIORITY -> RESEARCH DIRECTION
    computation (identical inputs/outputs to the background autonomous-
    research tick's own planning stage - Hotfix #168), plus the Korean
    rendering of its result. Returns ``(message, analysis, direction)`` so
    a caller with a real database connection can persist
    ``analysis``/``direction`` afterward without recomputing them."""
    analysis = analyze_mission_failure(mission, session_ref=session_id, now=now)
    priority = propose_research_priority(mission, None)
    has_untried_family = next_untried_family(candidate_records(mission)) is not None
    direction = plan_research_direction(
        analysis,
        priority,
        has_untried_family=has_untried_family,
        has_recoverable_candidate=False,
        now=now,
    )
    failure_label = _FAILURE_CLASS_LABEL_KO.get(analysis.dominant_failure_class, "미분류 사유")
    requirement = _EVIDENCE_REQUIREMENT_KO.get(analysis.dominant_failure_class, "사람의 검토")
    lines = [
        "영하님, 자동으로 확인한 결과는 다음과 같습니다.",
        "",
        mission_status_block(mission),
        "",
        render_blocked_reason_explanation(mission.blocked_reason),
        "",
        f"기존 후보들의 종료 사유를 분석한 결과 지배적 원인은 '{failure_label}'입니다.",
        f"지금 안전하게 자동으로 실행할 수 있는 추가 조치는 없으며, 다음 단계로 필요한 것은 {requirement}입니다.",
        "",
        "이 진단은 읽기 전용으로 자동 기록했을 뿐이며, 전략 config 변경, 후보 승격, 주문 실행, 승인 우회는 "
        "수행하지 않았습니다. 이 다음은 사람의 확인/승인이 필요한 부분만 남아 있습니다.",
    ]
    return "\n".join(lines), analysis, direction


def diagnose_structural_blocker(mission: ResearchMission, *, session_id: str, now: str) -> str:
    """Pure (no persistence, no recovery attempt) rendering of the same
    FAILURE ANALYSIS -> RESEARCH PRIORITY -> RESEARCH DIRECTION planning
    stage as :func:`attempt_structural_blocker_autonomous_continuation`'s
    no-recovery branch. Used directly by
    ``gaon.runtime.research_grounding.safe_capability_reply`` - a context
    with no database connection or tool-execution capability at all (it
    only ever replaces an already-generated provider reply's TEXT), so it
    can only ever state the concrete diagnosed next step, never execute
    anything. Never persists a ``ResearchDirection``/``FailureAnalysis``
    row itself - the caller with real connection access
    (``attempt_structural_blocker_autonomous_continuation``) owns
    persistence so there is exactly one write path, not two.
    """
    message, _analysis, _direction = _plan_and_render(mission, session_id=session_id, now=now)
    return message


def attempt_structural_blocker_autonomous_continuation(
    mission: ResearchMission,
    *,
    session_id: str,
    connection: sqlite3.Connection | None,
    now: str,
) -> StructuralBlockerContinuationOutcome:
    """Only ever meaningful when ``is_structural_hypothesis_space_blocker(mission)``
    is ``True`` - callers must check that first. Reuses
    ``attempt_bounded_stagnation_recovery`` (imported lazily to avoid the
    import cycle ``gaon.runtime.autonomous_research_runtime`` already has
    back into ``gaon.runtime.llm_conversation``) first; falls back to the
    same planning stage ``diagnose_structural_blocker`` renders when
    recovery finds nothing, persisting the analysis/direction idempotently
    via ``ResearchDirectionRepository`` exactly as the background worker
    does - a repeated call against an unchanged mission state is a cheap
    no-op read, never a duplicate row.
    """
    from gaon.runtime.autonomous_research_runtime import attempt_bounded_stagnation_recovery

    recovered_mission, recovered = attempt_bounded_stagnation_recovery(mission, now=now)
    if recovered:
        return StructuralBlockerContinuationOutcome(recovered_mission=recovered_mission, message=None)

    message, analysis, direction = _plan_and_render(mission, session_id=session_id, now=now)
    if connection is not None:
        repository = ResearchDirectionRepository(connection)
        repository.put_failure_analysis(analysis)
        repository.put_direction(direction)
    return StructuralBlockerContinuationOutcome(recovered_mission=None, message=message)
