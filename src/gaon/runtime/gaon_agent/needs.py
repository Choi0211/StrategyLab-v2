"""Need / gap reasoning model (foundation for PR #215).

When Gaon cannot fulfil a request it should not answer with a generic
apology. It should be able to say *what* is missing - a capability, some
data, evidence, a permission, user input, or possibly a code change - and
recommend a concrete next step.

PR #214 ships the typed model plus :func:`assess_from_registry`, a minimal
helper that turns "goal needs capability X" into a populated
:class:`NeedAssessment`. The full blocker-diagnosis engine is PR #215.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gaon.runtime.gaon_agent.capabilities import (
    CapabilityRegistry,
    CapabilityState,
)


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

    @property
    def is_fulfillable_now(self) -> bool:
        return (
            not self.missing_capabilities
            and not self.forbidden_capabilities
            and not self.missing_data
            and not self.user_input_required
        )


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
