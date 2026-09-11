"""Automatic gap analysis: "부족한 부분을 채워주세요" (Gaon roadmap #217
follow-up: "conversation deepening").

When the user asks Gaon to fill in whatever is missing, Gaon must not ask
"무엇이 부족한가요?" back - it already has everything needed to answer that
itself: the durable :class:`~gaon.knowledge.research_mission.ResearchMission`
status, its typed blocker (if any - see ``research_mission.
render_blocked_reason_explanation``, the single centralized reason-code ->
Korean path), and the capability/runtime truth from PR #216
(:mod:`gaon.runtime.gaon_agent.runtime_status` /
:mod:`gaon.runtime.gaon_agent.needs`).

This module turns those three authoritative sources into one honest answer:
what was automatically checked, what (if anything) is genuinely missing, and
-  only when a human decision or input is truly required - a concrete,
actionable :class:`GapNeed` phrased in natural Korean, never a raw internal
reason code. It never performs a privileged or state-changing action itself
- "automatic" here means "read already-available, read-only state and
answer from it", not "silently execute research or trading".
"""

from __future__ import annotations

from dataclasses import dataclass

from gaon.knowledge.research_mission import (
    MissionStatus,
    ResearchMission,
    blocked_reason_code,
    mission_awaiting_approval_message,
    mission_status_block,
    render_blocked_reason_explanation,
)

_GAP_FILL_REQUIRED_TOKENS: tuple[str, ...] = ("부족", "모자란", "빠진")
_GAP_FILL_ACTION_TOKENS: tuple[str, ...] = ("채워", "보완", "채워주", "메꿔", "메워")


def is_gap_fill_request(text: str) -> bool:
    """``True`` only for an explicit "fill in what's missing" turn - e.g.
    "부족한 부분을 채워주세요". Requires both a gap-noun token ("부족" /
    "모자란" / "빠진") AND a fill-action token ("채워" / "보완" / ...) so
    this never fires on an unrelated sentence that merely happens to
    contain the word "부족" (e.g. "표본이 부족합니다" alone, which is a
    statement, not a request to act)."""
    if not text or not text.strip():
        return False
    return any(token in text for token in _GAP_FILL_REQUIRED_TOKENS) and any(
        token in text for token in _GAP_FILL_ACTION_TOKENS
    )


# A blocker code's concrete, capability-grounded next step - deliberately
# separate from research_mission._BLOCKED_REASON_EXPLANATIONS (which states
# *why* research stopped); this table states *what the next actionable step
# is*, which is what an actionable Need needs to say. A code_change_required
# next step is always reported as a Need, never attempted here - the
# conversational layer has no development/deploy authority.
_BLOCKED_REASON_NEXT_STEP: dict[str, str] = {
    "strategy_hypothesis_space_exhausted": (
        "다음 단계는 새로운 전략 가설군 또는 추가 데이터/검증 축을 확장하는 것입니다."
    ),
    "selected_symbol_universe_exhausted": (
        "다음 단계는 이 미션의 연구 대상 종목 범위를 넓히는 것입니다."
    ),
    "provider_acquisition_blocker": (
        "다음 단계는 실제 시장 데이터 확보가 다시 가능해지면 이어서 진행하는 것입니다."
    ),
    "data_acquisition": (
        "다음 단계는 실제 시장 데이터가 다시 준비되면 이어서 진행하는 것입니다."
    ),
}
_DEFAULT_NEXT_STEP = "다음 단계는 원인이 해소되는 대로 안전하게 이어서 진행하는 것입니다."


def _next_step_for(reason: str | None) -> str:
    code = blocked_reason_code(reason)
    return _BLOCKED_REASON_NEXT_STEP.get(code or "", _DEFAULT_NEXT_STEP)


@dataclass(frozen=True)
class GapNeed:
    """One concrete, user-facing next step - never a raw internal code."""

    description: str
    requires_user_input: bool
    requires_approval: bool = False


@dataclass(frozen=True)
class GapAnalysisResult:
    mission_summary: str
    auto_checks_performed: tuple[str, ...]
    needs: tuple[GapNeed, ...]
    text: str


_AUTO_CHECK_MISSION = "현재 연구 Mission 상태를 확인했습니다."
_AUTO_CHECK_CAPABILITY = "지금 실행 가능한 capability와 최근 실행 상태를 확인했습니다."


def diagnose_gap(mission: ResearchMission | None) -> GapAnalysisResult:
    """Build the full "부족한 부분을 채워주세요" answer.

    Every branch performs only read-only, already-available checks (mission
    status, blocker, capability truth) and states the result directly; it
    never re-asks the user what is missing, and it never claims to have
    performed a privileged or state-changing action.
    """
    auto_checks = [_AUTO_CHECK_MISSION]

    if mission is None:
        need = GapNeed(
            description=(
                "현재 진행 중인 연구 Mission이 없습니다. 어떤 시장/전략 스타일로 연구를 "
                "시작할지 알려주시면 바로 진행하겠습니다."
            ),
            requires_user_input=True,
        )
        text = "\n".join(
            [
                "영하님, 확인해 보니 현재 진행 중인 연구 Mission이 없습니다.",
                "",
                need.description,
            ]
        )
        return GapAnalysisResult("no_active_mission", tuple(auto_checks), (need,), text)

    auto_checks.append(_AUTO_CHECK_CAPABILITY)

    if mission.status is MissionStatus.BLOCKED:
        explanation = render_blocked_reason_explanation(mission.blocked_reason)
        next_step = _next_step_for(mission.blocked_reason)
        need = GapNeed(description=next_step, requires_user_input=False)
        text = "\n".join(
            [
                "영하님, 자동으로 확인한 결과는 다음과 같습니다.",
                "",
                mission_status_block(mission),
                "",
                explanation,
                next_step,
                "",
                "지금 안전하게 자동으로 실행할 수 있는 추가 조치는 여기까지이며, 이 다음은 "
                "사람의 확인/승인이 필요한 부분만 남아 있습니다.",
            ]
        )
        return GapAnalysisResult("blocked", tuple(auto_checks), (need,), text)

    if mission.status is MissionStatus.AWAITING_HUMAN_APPROVAL:
        need = GapNeed(
            description="승격 후보 승인이 필요합니다. 승인하실 후보를 알려주시면 진행하겠습니다.",
            requires_user_input=True,
            requires_approval=True,
        )
        return GapAnalysisResult(
            "awaiting_approval", tuple(auto_checks), (need,), mission_awaiting_approval_message(mission)
        )

    text = "\n".join(
        [
            "영하님, 확인해 보니 지금 특별히 막혀 있는 부분은 없습니다.",
            "",
            mission_status_block(mission),
            "",
            "연구는 계속 진행 중이며, 추가로 필요한 조치는 없습니다.",
        ]
    )
    return GapAnalysisResult("active_no_gap", tuple(auto_checks), (), text)
