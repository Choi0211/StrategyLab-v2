"""Need / gap reasoning model (foundation for PR #215).

When Gaon cannot fulfil a request it should not answer with a generic
apology. It should be able to say *what* is missing - a capability, some
data, evidence, a permission, user input, or possibly a code change - and
recommend a concrete next step.

PR #214 ships the typed model plus :func:`assess_from_registry`, a minimal
helper that turns "goal needs capability X" into a populated
:class:`NeedAssessment`. The Capability & Need Registry work adds
:func:`diagnose`, which layers the
runtime-availability observation (see
:mod:`gaon.runtime.gaon_agent.runtime_status`) and the other gap kinds on
top, so a blocked request can be explained as one of a fixed, typed set of
:class:`BlockerKind` values with a concrete next step - and, crucially, so
"the provider is offline" is diagnosed distinctly from "this capability is
not implemented" and never confused with a policy state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from gaon.runtime.gaon_agent.capabilities import (
    CapabilityRegistry,
    CapabilityState,
)
from gaon.runtime.gaon_agent.runtime_status import (
    CapabilityRuntimeObservation,
    RuntimeAvailability,
    RuntimeReason,
)


class BlockerKind(str, Enum):
    """The fixed, typed vocabulary of *why* a request cannot be fulfilled
    right now. Operational kinds (``PROVIDER_*``) are deliberately separate
    from the policy kinds (``APPROVAL_REQUIRED`` / ``FORBIDDEN_BY_SAFETY``)
    and from the not-implemented kind (``CAPABILITY_UNAVAILABLE``)."""

    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    PROVIDER_OFFLINE = "provider_offline"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_DEGRADED = "provider_degraded"
    CONFIGURATION_DISABLED = "configuration_disabled"
    MISSING_USER_INPUT = "missing_user_input"
    MISSING_DATA = "missing_data"
    MISSING_EVIDENCE = "missing_evidence"
    APPROVAL_REQUIRED = "approval_required"
    FORBIDDEN_BY_SAFETY = "forbidden_by_safety"
    CODE_CHANGE_REQUIRED = "code_change_required"


@dataclass(frozen=True)
class Blocker:
    """One concrete reason a goal is blocked, with a user-facing next step.

    ``explanation`` and ``next_step`` are short Korean sentences safe to show
    the user; they never contain provider internals, secrets or addresses.
    """

    kind: BlockerKind
    capability_id: str | None
    explanation: str
    next_step: str
    detail: str = ""


@dataclass(frozen=True)
class RequestedGoal:
    description: str
    required_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class NeedAssessment:
    goal: RequestedGoal
    available_capabilities: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()
    approval_required_capabilities: tuple[str, ...] = ()
    forbidden_capabilities: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    user_input_required: tuple[str, ...] = ()
    code_change_potentially_required: bool = False
    recommended_next_step: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    # Capability & Need Registry: capabilities that are *configured* AVAILABLE but whose
    # provider is currently unreachable / timing out / disabled, plus the
    # typed blocker list built by :func:`diagnose`. Both default empty so
    # every existing :class:`NeedAssessment` construction is unchanged.
    runtime_unavailable_capabilities: tuple[str, ...] = ()
    blockers: tuple[Blocker, ...] = ()

    @property
    def is_fulfillable_now(self) -> bool:
        return (
            not self.missing_capabilities
            and not self.forbidden_capabilities
            and not self.missing_data
            and not self.user_input_required
            and not self.runtime_unavailable_capabilities
            and not self.blockers
        )

    @property
    def primary_blocker(self) -> Blocker | None:
        return self.blockers[0] if self.blockers else None


def assess_from_registry(goal: RequestedGoal, registry: CapabilityRegistry) -> NeedAssessment:
    """Partition ``goal.required_capabilities`` by their registry state and
    recommend the obvious next step."""
    available: list[str] = []
    missing: list[str] = []
    approval: list[str] = []
    forbidden: list[str] = []
    code_change = False

    for capability_id in goal.required_capabilities:
        state = registry.state(capability_id)
        if state is CapabilityState.AVAILABLE:
            available.append(capability_id)
        elif state is CapabilityState.APPROVAL_REQUIRED:
            approval.append(capability_id)
        elif state is CapabilityState.FORBIDDEN:
            forbidden.append(capability_id)
        else:
            missing.append(capability_id)
            capability = registry.get(capability_id)
            if capability is not None and capability.safety_class.value in {"read_only", "research", "development"}:
                code_change = True

    if forbidden:
        next_step = (
            "This needs a privileged action that the conversational layer must not perform. "
            "It has to go through its dedicated approval / safety controller."
        )
    elif missing:
        next_step = (
            "A capability is not wired yet: "
            + ", ".join(missing)
            + ". This is a code change - it can be proposed as development work (see the roadmap)."
        )
    elif approval:
        next_step = "Ready to proceed once you give an explicit instruction and approve the human gate."
    elif available:
        next_step = "All required capabilities are available; proceed."
    else:
        next_step = "No capability requirement recorded for this goal."

    return NeedAssessment(
        goal=goal,
        available_capabilities=tuple(available),
        missing_capabilities=tuple(missing),
        approval_required_capabilities=tuple(approval),
        forbidden_capabilities=tuple(forbidden),
        code_change_potentially_required=code_change,
        recommended_next_step=next_step,
    )


_RUNTIME_BLOCKER_KIND: dict[RuntimeReason, BlockerKind] = {
    RuntimeReason.PROVIDER_UNREACHABLE: BlockerKind.PROVIDER_OFFLINE,
    RuntimeReason.PROVIDER_TIMEOUT: BlockerKind.PROVIDER_TIMEOUT,
    RuntimeReason.PROVIDER_DISABLED: BlockerKind.CONFIGURATION_DISABLED,
}


def _runtime_blocker(capability_id: str, observation: CapabilityRuntimeObservation) -> Blocker | None:
    """Turn a runtime observation on a *configured-AVAILABLE* capability into
    a typed :class:`Blocker`, or ``None`` when it is genuinely usable / its
    state is merely unknown."""
    if observation.availability in (RuntimeAvailability.AVAILABLE, RuntimeAvailability.UNKNOWN):
        return None
    if observation.availability is RuntimeAvailability.DEGRADED and observation.reason is RuntimeReason.PROVIDER_TIMEOUT:
        return Blocker(
            kind=BlockerKind.PROVIDER_TIMEOUT,
            capability_id=capability_id,
            explanation="대화용 AI 모델 응답이 지연되고 있습니다.",
            next_step="잠시 후 다시 시도해 주세요. 그동안 연구·전략 상태 확인 같은 서버 기능은 계속 사용할 수 있습니다.",
            detail=observation.detail,
        )
    kind = _RUNTIME_BLOCKER_KIND.get(observation.reason, BlockerKind.PROVIDER_OFFLINE)
    if kind is BlockerKind.CONFIGURATION_DISABLED:
        explanation = "대화용 AI 모델이 꺼져 있습니다."
    else:
        explanation = "대화용 AI 모델에 연결할 수 없습니다."
    return Blocker(
        kind=kind,
        capability_id=capability_id,
        explanation=explanation,
        next_step="연구 미션·전략 상태 확인 등 서버 기능은 계속 사용할 수 있습니다. 모델이 다시 연결되면 일반 대화도 정상 동작합니다.",
        detail=observation.detail,
    )


def diagnose(
    goal: RequestedGoal,
    registry: CapabilityRegistry,
    *,
    runtime_observations: dict[str, CapabilityRuntimeObservation] | None = None,
    missing_user_input: tuple[str, ...] = (),
    missing_data: tuple[str, ...] = (),
    missing_evidence: tuple[str, ...] = (),
) -> NeedAssessment:
    """The blocker-diagnosis engine.

    Starts from :func:`assess_from_registry` (policy partition) and layers
    on: the runtime availability of each *configured-AVAILABLE* required
    capability, plus any caller-supplied missing user input / data /
    evidence. The result carries a typed :class:`Blocker` list ordered
    hardest-first: safety boundary, then not-implemented, then operational
    provider state, then missing inputs, then approval.

    Runtime state can only ever *remove* a capability from
    ``available_capabilities`` (into ``runtime_unavailable_capabilities``);
    it never promotes a missing / approval / forbidden capability. A
    ``FORBIDDEN`` capability stays forbidden and a timed-out provider does
    not change that.
    """
    base = assess_from_registry(goal, registry)
    observations = runtime_observations or {}

    runtime_unavailable: list[str] = []
    still_available: list[str] = []
    runtime_blockers: list[Blocker] = []
    for capability_id in base.available_capabilities:
        observation = observations.get(capability_id)
        blocker = _runtime_blocker(capability_id, observation) if observation is not None else None
        if blocker is None:
            still_available.append(capability_id)
            continue
        runtime_unavailable.append(capability_id)
        runtime_blockers.append(blocker)

    blockers: list[Blocker] = []
    for capability_id in base.forbidden_capabilities:
        capability = registry.get(capability_id)
        blockers.append(
            Blocker(
                kind=BlockerKind.FORBIDDEN_BY_SAFETY,
                capability_id=capability_id,
                explanation="이 작업은 대화/에이전트 계층에서 수행할 수 없습니다.",
                next_step="전용 승인·안전 컨트롤러를 통해서만 진행할 수 있습니다.",
                detail=capability.summary if capability is not None else "",
            )
        )
    for capability_id in base.missing_capabilities:
        capability = registry.get(capability_id)
        blockers.append(
            Blocker(
                kind=BlockerKind.CAPABILITY_UNAVAILABLE,
                capability_id=capability_id,
                explanation="아직 연결되지 않은 기능입니다.",
                next_step="개발 작업으로 제안할 수 있습니다 (로드맵 참고).",
                detail=(capability.reason or "") if capability is not None else "",
            )
        )
    blockers.extend(runtime_blockers)
    for item in missing_user_input:
        blockers.append(
            Blocker(
                kind=BlockerKind.MISSING_USER_INPUT,
                capability_id=None,
                explanation="요청을 수행하려면 추가 정보가 필요합니다.",
                next_step=f"{item} 정보를 알려주시면 진행할 수 있습니다.",
                detail=item,
            )
        )
    for item in missing_data:
        blockers.append(
            Blocker(
                kind=BlockerKind.MISSING_DATA,
                capability_id=None,
                explanation="필요한 데이터가 아직 준비되지 않았습니다.",
                next_step=f"{item} 데이터가 확보되면 진행할 수 있습니다.",
                detail=item,
            )
        )
    for item in missing_evidence:
        blockers.append(
            Blocker(
                kind=BlockerKind.MISSING_EVIDENCE,
                capability_id=None,
                explanation="근거(Evidence)가 아직 검증되지 않았습니다.",
                next_step=f"{item}에 대한 출처가 확인되면 검토를 이어갈 수 있습니다.",
                detail=item,
            )
        )
    for capability_id in base.approval_required_capabilities:
        blockers.append(
            Blocker(
                kind=BlockerKind.APPROVAL_REQUIRED,
                capability_id=capability_id,
                explanation="명시적 요청과 사람 승인이 필요합니다.",
                next_step="명확히 지시해 주시고 승인 게이트를 통과하면 진행합니다.",
            )
        )

    primary = blockers[0] if blockers else None
    next_step = primary.next_step if primary is not None else base.recommended_next_step

    return NeedAssessment(
        goal=goal,
        available_capabilities=tuple(still_available),
        missing_capabilities=base.missing_capabilities,
        approval_required_capabilities=base.approval_required_capabilities,
        forbidden_capabilities=base.forbidden_capabilities,
        missing_data=tuple(missing_data),
        missing_evidence=tuple(missing_evidence),
        user_input_required=tuple(missing_user_input),
        code_change_potentially_required=base.code_change_potentially_required,
        recommended_next_step=next_step,
        notes=base.notes,
        runtime_unavailable_capabilities=tuple(runtime_unavailable),
        blockers=tuple(blockers),
    )
