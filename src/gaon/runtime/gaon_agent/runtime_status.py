"""Runtime availability observation layer - part of "Gaon Capability & Need
Registry: Runtime Truth & Blocker Diagnosis" (roadmap item #215).

The :class:`~gaon.runtime.gaon_agent.capabilities.CapabilityRegistry` is the
authoritative record of what Gaon is *configured* to do and what policy state
guards each ability (``AVAILABLE`` / ``UNAVAILABLE`` / ``APPROVAL_REQUIRED`` /
``FORBIDDEN``). That is a static, deterministic contract and this module does
**not** change it.

What it adds is a strictly separate, observational answer to a different
question: *is a provider-backed capability actually reachable right now?*

Production topology for ``GENERAL_CONVERSATION``::

    Gaon VPS  ->  Tailscale  ->  user PC  ->  Ollama / qwen3:8b

so the moment the PC or Ollama is off, natural LLM conversation is
unavailable even though it is still *configured* and *policy-allowed*. Gaon
must say so honestly instead of dropping to a generic "요청을 이해하지
못했습니다" fallback that reads as a comprehension failure.

Design rules this layer obeys:

* **Policy dominates.** :meth:`ProviderRuntimeMonitor.observe` can only ever
  return :data:`RuntimeAvailability.AVAILABLE` when the *configured* state is
  ``AVAILABLE``. A ``FORBIDDEN`` or ``APPROVAL_REQUIRED`` capability is never
  turned into something usable by any provider-health signal, and provider
  health is never even consulted for it. ``TRADING_EXECUTION`` stays
  ``FORBIDDEN`` whether the network is up or down.
* **Operational != policy.** "the provider is down" is reported as its own
  :class:`RuntimeReason`; it never overwrites or masquerades as a policy
  state.
* **No permission is granted here.** Nothing an LLM says ("mark
  ``TRADING_EXECUTION`` available") can reach this layer, and this layer
  cannot widen any privileged boundary. It only ever *narrows* an
  ``AVAILABLE`` capability to a runtime-unavailable observation.
* **Cheap.** No health request is made from here. The monitor reuses the
  outcome of the assistant-provider call the conversation already makes, kept
  in a bounded-TTL cache; when the last signal is older than the TTL the
  honest answer is :data:`RuntimeAvailability.UNKNOWN`, never a guessed
  ``AVAILABLE``.
* **Fail closed / honest degradation.** Secrets, API keys, full provider
  URLs and Tailscale addresses never appear in an observation ``detail``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from gaon.runtime.gaon_agent.capabilities import (
    GENERAL_CONVERSATION,
    CapabilityRegistry,
    CapabilityState,
)

# The only capability whose real availability depends on an external
# assistant provider being reachable. Everything else is served by
# deterministic, in-process read models and is therefore unaffected by
# provider health. A later PR that wires a real WEB_SEARCH / URL_FETCH
# provider adds its id here.
PROVIDER_BACKED_CAPABILITIES: frozenset[str] = frozenset({GENERAL_CONVERSATION})

# How long a recorded provider outcome is treated as still describing
# "now". A conversation turn takes well under this, so a healthy turn keeps
# the next turn's observation fresh without any extra probing; once traffic
# stops for longer than this the honest answer becomes UNKNOWN.
DEFAULT_OBSERVATION_TTL_SECONDS = 90


class RuntimeAvailability(str, Enum):
    """Observed, operational availability - distinct from policy state."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class RuntimeReason(str, Enum):
    HEALTHY = "healthy"
    PROVIDER_UNREACHABLE = "provider_unreachable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_DISABLED = "provider_disabled"
    NOT_PROVIDER_BACKED = "not_provider_backed"
    NO_RECENT_SIGNAL = "no_recent_signal"
    POLICY_NOT_AVAILABLE = "policy_not_available"


class RuntimeObservationSource(str, Enum):
    PROVIDER_CALL = "provider_call"
    HEALTH_PROBE = "health_probe"
    STATIC = "static"


@dataclass(frozen=True)
class CapabilityRuntimeObservation:
    """A point-in-time, operational read on one capability.

    ``detail`` is a short, user-safe phrase only: never a secret, an API
    key, a full provider URL or a Tailscale address.
    """

    capability_id: str
    availability: RuntimeAvailability
    provider: str | None
    observed_at: str
    reason: RuntimeReason
    detail: str = ""
    source: RuntimeObservationSource = RuntimeObservationSource.STATIC

    @property
    def is_available(self) -> bool:
        return self.availability is RuntimeAvailability.AVAILABLE

    @property
    def is_known_unavailable(self) -> bool:
        return self.availability in (
            RuntimeAvailability.UNAVAILABLE,
            RuntimeAvailability.DEGRADED,
        )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Only these assistant-provider failures are evidence about *availability*.
# A safety / parse / grounding rejection means the provider answered but its
# output was refused - a content problem, usually transient - and must NOT
# be recorded as "the conversation model is unreachable".
_CONNECTIVITY_MARKERS: tuple[str, ...] = (
    "timeout",
    "timed out",
    "unavailable",
    "unreachable",
    "disabled",
    "connection",
    "refused",
    "unhealthy",
    "network",
    "provider error: providerunavailableerror",
    "provider error: providertimeouterror",
)


def is_connectivity_error(error_type: str) -> bool:
    """True when ``error_type`` (an exception class name or a routing-layer
    fallback-warning string) describes a provider *availability* failure
    rather than a content / safety rejection."""
    lowered = error_type.lower()
    if "safety" in lowered or "parse" in lowered or "grounding" in lowered:
        return False
    return any(marker in lowered for marker in _CONNECTIVITY_MARKERS)


def classify_provider_error(error_type: str) -> tuple[RuntimeAvailability, RuntimeReason]:
    """Map an assistant-provider error class name to an observation.

    A timeout is ``DEGRADED`` (the provider may still be up, just slow); a
    refused connection / disabled provider / any other failure is a hard
    ``UNAVAILABLE``.
    """
    lowered = error_type.lower()
    if "timeout" in lowered:
        return RuntimeAvailability.DEGRADED, RuntimeReason.PROVIDER_TIMEOUT
    if "disabled" in lowered:
        return RuntimeAvailability.UNAVAILABLE, RuntimeReason.PROVIDER_DISABLED
    return RuntimeAvailability.UNAVAILABLE, RuntimeReason.PROVIDER_UNREACHABLE


@dataclass(frozen=True)
class _Outcome:
    availability: RuntimeAvailability
    reason: RuntimeReason
    provider: str | None
    at: str
    detail: str
    source: RuntimeObservationSource


class ProviderRuntimeMonitor:
    """Bounded-TTL cache of the most recent assistant-provider outcome.

    The conversation brain records the result of the provider call it
    already makes (success / timeout / connection error / disabled). Any
    component that needs to know whether ``GENERAL_CONVERSATION`` is usable
    right now asks :meth:`observe`, which never performs a network request.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_OBSERVATION_TTL_SECONDS,
        provider_backed_capabilities: frozenset[str] = PROVIDER_BACKED_CAPABILITIES,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._provider_backed = provider_backed_capabilities
        self._last: _Outcome | None = None

    # -- recording ------------------------------------------------------
    def record_success(self, *, provider: str, now: str, latency_ms: int | None = None) -> None:
        detail = f"응답 확인 (약 {latency_ms}ms)" if isinstance(latency_ms, int) and latency_ms >= 0 else "응답 확인"
        self._last = _Outcome(
            RuntimeAvailability.AVAILABLE,
            RuntimeReason.HEALTHY,
            provider,
            now,
            detail,
            RuntimeObservationSource.PROVIDER_CALL,
        )

    def record_failure(self, *, provider: str, now: str, error_type: str) -> None:
        availability, reason = classify_provider_error(error_type)
        detail = {
            RuntimeReason.PROVIDER_TIMEOUT: "응답이 시간 안에 오지 않음",
            RuntimeReason.PROVIDER_DISABLED: "대화 모델이 꺼져 있음",
            RuntimeReason.PROVIDER_UNREACHABLE: "대화 모델에 연결할 수 없음",
        }.get(reason, "대화 모델에 연결할 수 없음")
        self._last = _Outcome(
            availability,
            reason,
            provider,
            now,
            detail,
            RuntimeObservationSource.PROVIDER_CALL,
        )

    def record_disabled(self, *, provider: str, now: str) -> None:
        self._last = _Outcome(
            RuntimeAvailability.UNAVAILABLE,
            RuntimeReason.PROVIDER_DISABLED,
            provider,
            now,
            "대화 모델이 꺼져 있음",
            RuntimeObservationSource.STATIC,
        )

    def forget(self) -> None:
        self._last = None

    # -- reading ------------------------------------------------------
    def observe(
        self,
        capability_id: str,
        *,
        now: str,
        configured_state: CapabilityState,
    ) -> CapabilityRuntimeObservation:
        # Policy dominates: a capability that is not configured AVAILABLE is
        # never reported runtime-AVAILABLE, and provider health is not even
        # consulted for it. This is the invariant that keeps FORBIDDEN /
        # APPROVAL_REQUIRED immune to any operational signal.
        if configured_state is not CapabilityState.AVAILABLE:
            return CapabilityRuntimeObservation(
                capability_id=capability_id,
                availability=RuntimeAvailability.UNAVAILABLE,
                provider=None,
                observed_at="",
                reason=RuntimeReason.POLICY_NOT_AVAILABLE,
                detail=f"정책 상태: {configured_state.value}",
                source=RuntimeObservationSource.STATIC,
            )

        # Configured AVAILABLE, but served in-process - provider health is
        # irrelevant, it is simply available.
        if capability_id not in self._provider_backed:
            return CapabilityRuntimeObservation(
                capability_id=capability_id,
                availability=RuntimeAvailability.AVAILABLE,
                provider=None,
                observed_at="",
                reason=RuntimeReason.NOT_PROVIDER_BACKED,
                detail="서버 내부 기능",
                source=RuntimeObservationSource.STATIC,
            )

        # Provider-backed: answer from the last recorded outcome if it is
        # still fresh; otherwise be honest that we do not currently know.
        outcome = self._last
        if outcome is None or self._is_stale(outcome.at, now):
            return CapabilityRuntimeObservation(
                capability_id=capability_id,
                availability=RuntimeAvailability.UNKNOWN,
                provider=None,
                observed_at="",
                reason=RuntimeReason.NO_RECENT_SIGNAL,
                detail="최근 확인 기록이 없음",
                source=RuntimeObservationSource.STATIC,
            )
        return CapabilityRuntimeObservation(
            capability_id=capability_id,
            availability=outcome.availability,
            provider=outcome.provider,
            observed_at=outcome.at,
            reason=outcome.reason,
            detail=outcome.detail,
            source=outcome.source,
        )

    def _is_stale(self, at: str, now: str) -> bool:
        try:
            return _parse_utc(now) - _parse_utc(at) > self._ttl
        except ValueError:
            # An unparseable timestamp is treated as no usable signal.
            return True


def resolve_runtime_observations(
    registry: CapabilityRegistry,
    monitor: ProviderRuntimeMonitor,
    *,
    now: str,
) -> tuple[CapabilityRuntimeObservation, ...]:
    """One :class:`CapabilityRuntimeObservation` per capability in the
    registry, in registry order."""
    return tuple(
        monitor.observe(capability.id, now=now, configured_state=capability.state)
        for capability in registry.all()
    )


def observation_index(
    observations: tuple[CapabilityRuntimeObservation, ...],
) -> dict[str, CapabilityRuntimeObservation]:
    return {obs.capability_id: obs for obs in observations}


def general_conversation_runtime(
    registry: CapabilityRegistry,
    monitor: ProviderRuntimeMonitor,
    *,
    now: str,
) -> CapabilityRuntimeObservation:
    capability = registry.get(GENERAL_CONVERSATION)
    state = capability.state if capability is not None else CapabilityState.UNAVAILABLE
    return monitor.observe(GENERAL_CONVERSATION, now=now, configured_state=state)


def runtime_capability_note(observation: CapabilityRuntimeObservation) -> str:
    """A single short, user-safe Korean sentence describing why natural LLM
    conversation is currently limited - or an empty string when it is fine
    or its state is unknown. Never leaks provider internals."""
    if observation.availability is RuntimeAvailability.DEGRADED:
        # Keep the canonical "로컬 LLM 응답이 지연" phrasing the rest of the
        # runtime uses for a slow model (research_failures.py,
        # _provider_unavailable_message), then add the honest note that the
        # server-native reads are unaffected.
        return (
            "지금은 로컬 LLM 응답이 지연되고 있습니다, 영하님. "
            "연구 미션·전략 상태 확인 같은 서버 기능은 계속 사용할 수 있으니 잠시 후 다시 시도해 주세요."
        )
    if observation.availability is RuntimeAvailability.UNAVAILABLE:
        return (
            "지금은 대화용 AI 모델에 연결할 수 없어 자유로운 일반 대화는 제한됩니다. "
            "연구 미션·전략 상태 확인 같은 서버 기능은 정상 사용할 수 있습니다."
        )
    return ""
