"""Gaon Capability & Need Registry: Runtime Truth & Blocker Diagnosis
(roadmap item #215).

Unit coverage for the runtime-observation layer
(:mod:`gaon.runtime.gaon_agent.runtime_status`) and the blocker-diagnosis
engine (:func:`gaon.runtime.gaon_agent.needs.diagnose`).

The invariant these tests exist to protect: a provider-health signal can
only ever *narrow* a configured-``AVAILABLE`` capability to a
runtime-unavailable observation. It can never turn ``FORBIDDEN`` or
``APPROVAL_REQUIRED`` into anything usable, and "the provider is offline" is
diagnosed as its own typed blocker, never confused with a policy state.
"""

from __future__ import annotations

import unittest

from gaon.runtime.gaon_agent import (
    BlockerKind,
    ProviderRuntimeMonitor,
    RequestedGoal,
    RuntimeAvailability,
    RuntimeReason,
    default_capability_registry,
    diagnose,
    general_conversation_runtime,
    resolve_runtime_observations,
    observation_index,
    runtime_capability_note,
)
from gaon.runtime.gaon_agent.capabilities import (
    CHAMPION_PROMOTION,
    GENERAL_CONVERSATION,
    RESEARCH_MISSION_READ,
    RESEARCH_MISSION_RUN,
    STRATEGY_STATUS_READ,
    TRADING_EXECUTION,
    URL_FETCH,
    CapabilityState,
)
from gaon.runtime.gaon_agent.runtime_status import (
    classify_provider_error,
    is_connectivity_error,
)

T0 = "2026-09-10T00:00:00Z"
T_SOON = "2026-09-10T00:00:30Z"
T_LATER = "2026-09-10T00:05:00Z"  # > default 90s TTL after T0


class ProviderRuntimeMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_capability_registry()

    def _observe_general(self, monitor: ProviderRuntimeMonitor, now: str):
        return general_conversation_runtime(self.registry, monitor, now=now)

    def test_provider_healthy_makes_general_conversation_runtime_available(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_success(provider="openai-compatible", now=T0, latency_ms=120)
        obs = self._observe_general(monitor, T_SOON)
        self.assertEqual(obs.availability, RuntimeAvailability.AVAILABLE)
        self.assertEqual(obs.reason, RuntimeReason.HEALTHY)
        self.assertTrue(obs.is_available)

    def test_provider_unreachable_makes_runtime_unavailable(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_failure(
            provider="openai-compatible", now=T0, error_type="ProviderUnavailableError"
        )
        obs = self._observe_general(monitor, T_SOON)
        self.assertEqual(obs.availability, RuntimeAvailability.UNAVAILABLE)
        self.assertEqual(obs.reason, RuntimeReason.PROVIDER_UNREACHABLE)
        self.assertFalse(obs.is_available)
        self.assertTrue(obs.is_known_unavailable)

    def test_provider_timeout_makes_runtime_degraded(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_failure(
            provider="openai-compatible", now=T0, error_type="ProviderTimeoutError"
        )
        obs = self._observe_general(monitor, T_SOON)
        self.assertEqual(obs.availability, RuntimeAvailability.DEGRADED)
        self.assertEqual(obs.reason, RuntimeReason.PROVIDER_TIMEOUT)

    def test_provider_disabled_is_a_distinct_reason(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_failure(
            provider="openai-compatible", now=T0, error_type="assistant provider is disabled"
        )
        obs = self._observe_general(monitor, T_SOON)
        self.assertEqual(obs.availability, RuntimeAvailability.UNAVAILABLE)
        self.assertEqual(obs.reason, RuntimeReason.PROVIDER_DISABLED)

    def test_stale_signal_is_unknown_not_a_guessed_available(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_success(provider="openai-compatible", now=T0)
        obs = self._observe_general(monitor, T_LATER)
        self.assertEqual(obs.availability, RuntimeAvailability.UNKNOWN)
        self.assertEqual(obs.reason, RuntimeReason.NO_RECENT_SIGNAL)

    def test_no_signal_at_all_is_unknown(self) -> None:
        obs = self._observe_general(ProviderRuntimeMonitor(), T0)
        self.assertEqual(obs.availability, RuntimeAvailability.UNKNOWN)

    def test_observation_detail_never_leaks_provider_internals(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_failure(
            provider="openai-compatible",
            now=T0,
            error_type="ProviderUnavailableError",
        )
        for now in (T_SOON, T_LATER):
            obs = self._observe_general(monitor, now)
            blob = f"{obs.detail} {obs.provider or ''}".lower()
            for leak in ("http", "://", "bearer", "api_key", "sk-", "100.", "127.0.0.1", "tailscale", "qwen"):
                self.assertNotIn(leak, blob)

    def test_non_provider_backed_available_capability_is_runtime_available(self) -> None:
        """A configured-AVAILABLE, in-process read model is not affected by
        provider health - even a hard provider failure leaves it usable."""
        monitor = ProviderRuntimeMonitor()
        monitor.record_failure(
            provider="openai-compatible", now=T0, error_type="ProviderUnavailableError"
        )
        for capability_id in (RESEARCH_MISSION_READ, STRATEGY_STATUS_READ):
            obs = monitor.observe(
                capability_id, now=T_SOON, configured_state=CapabilityState.AVAILABLE
            )
            self.assertEqual(obs.availability, RuntimeAvailability.AVAILABLE, capability_id)
            self.assertEqual(obs.reason, RuntimeReason.NOT_PROVIDER_BACKED, capability_id)

    def test_forbidden_capability_is_never_runtime_available_even_with_healthy_provider(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_success(provider="openai-compatible", now=T0)
        obs = monitor.observe(
            TRADING_EXECUTION, now=T_SOON, configured_state=CapabilityState.FORBIDDEN
        )
        self.assertNotEqual(obs.availability, RuntimeAvailability.AVAILABLE)
        self.assertEqual(obs.availability, RuntimeAvailability.UNAVAILABLE)
        self.assertEqual(obs.reason, RuntimeReason.POLICY_NOT_AVAILABLE)

    def test_approval_required_capability_is_never_runtime_available(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_success(provider="openai-compatible", now=T0)
        obs = monitor.observe(
            RESEARCH_MISSION_RUN, now=T_SOON, configured_state=CapabilityState.APPROVAL_REQUIRED
        )
        self.assertNotEqual(obs.availability, RuntimeAvailability.AVAILABLE)
        self.assertEqual(obs.reason, RuntimeReason.POLICY_NOT_AVAILABLE)

    def test_resolve_runtime_observations_covers_every_registry_capability(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_success(provider="openai-compatible", now=T0)
        observations = resolve_runtime_observations(self.registry, monitor, now=T_SOON)
        index = observation_index(observations)
        self.assertEqual(set(index), {c.id for c in self.registry.all()})
        # forbidden ids never come back AVAILABLE
        for capability in self.registry.by_state(CapabilityState.FORBIDDEN):
            self.assertNotEqual(index[capability.id].availability, RuntimeAvailability.AVAILABLE)

    def test_runtime_capability_note_is_empty_unless_known_unavailable(self) -> None:
        monitor = ProviderRuntimeMonitor()
        # unknown -> no note (never guess)
        self.assertEqual(runtime_capability_note(self._observe_general(monitor, T0)), "")
        monitor.record_success(provider="openai-compatible", now=T0)
        self.assertEqual(runtime_capability_note(self._observe_general(monitor, T_SOON)), "")
        monitor.record_failure(
            provider="openai-compatible", now=T_SOON, error_type="ProviderUnavailableError"
        )
        note = runtime_capability_note(self._observe_general(monitor, T_SOON))
        self.assertIn("연결할 수 없", note)
        self.assertIn("서버 기능", note)
        for leak in ("http", "tailscale", "qwen", "api"):
            self.assertNotIn(leak, note.lower())

    def test_is_connectivity_error_separates_availability_from_content_failures(self) -> None:
        for connectivity in (
            "ProviderTimeoutError",
            "ProviderUnavailableError",
            "assistant provider is disabled",
            "provider error: ProviderUnavailableError",
            "connection refused",
            "provider unhealthy: openai-compatible",
        ):
            self.assertTrue(is_connectivity_error(connectivity), connectivity)
        for content in (
            "ProviderSafetyError",
            "provider returned empty response",
            "grounding violation",
            "malformed content parse failure",
            "ProviderError",
        ):
            self.assertFalse(is_connectivity_error(content), content)

    def test_non_connectivity_failure_leaves_runtime_state_untouched(self) -> None:
        monitor = ProviderRuntimeMonitor()
        monitor.record_success(provider="openai-compatible", now=T0)
        # a later safety rejection is a content problem, not an availability
        # signal - the caller simply does not call record_failure for it, so
        # the last known-good signal still stands within the TTL.
        obs = self._observe_general(monitor, T_SOON)
        self.assertEqual(obs.availability, RuntimeAvailability.AVAILABLE)

    def test_classify_provider_error_mapping(self) -> None:
        self.assertEqual(
            classify_provider_error("ProviderTimeoutError"),
            (RuntimeAvailability.DEGRADED, RuntimeReason.PROVIDER_TIMEOUT),
        )
        self.assertEqual(
            classify_provider_error("provider is disabled"),
            (RuntimeAvailability.UNAVAILABLE, RuntimeReason.PROVIDER_DISABLED),
        )
        self.assertEqual(
            classify_provider_error("ConnectionRefusedError"),
            (RuntimeAvailability.UNAVAILABLE, RuntimeReason.PROVIDER_UNREACHABLE),
        )


class DiagnoseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_capability_registry()
        self.monitor = ProviderRuntimeMonitor()

    def _observations(self, now: str):
        return observation_index(
            resolve_runtime_observations(self.registry, self.monitor, now=now)
        )

    def test_provider_offline_blocks_a_general_conversation_goal(self) -> None:
        self.monitor.record_failure(
            provider="openai-compatible", now=T0, error_type="ProviderUnavailableError"
        )
        goal = RequestedGoal("자유 대화", required_capabilities=(GENERAL_CONVERSATION,))
        assessment = diagnose(
            goal, self.registry, runtime_observations=self._observations(T_SOON)
        )
        self.assertFalse(assessment.is_fulfillable_now)
        self.assertEqual(assessment.runtime_unavailable_capabilities, (GENERAL_CONVERSATION,))
        self.assertEqual(assessment.available_capabilities, ())
        self.assertIsNotNone(assessment.primary_blocker)
        self.assertEqual(assessment.primary_blocker.kind, BlockerKind.PROVIDER_OFFLINE)
        self.assertEqual(assessment.primary_blocker.capability_id, GENERAL_CONVERSATION)

    def test_provider_timeout_is_its_own_blocker_kind(self) -> None:
        self.monitor.record_failure(
            provider="openai-compatible", now=T0, error_type="ProviderTimeoutError"
        )
        goal = RequestedGoal("자유 대화", required_capabilities=(GENERAL_CONVERSATION,))
        assessment = diagnose(
            goal, self.registry, runtime_observations=self._observations(T_SOON)
        )
        self.assertEqual(assessment.primary_blocker.kind, BlockerKind.PROVIDER_TIMEOUT)
        self.assertRegex(assessment.recommended_next_step, r"(다시 시도|서버 기능)")

    def test_healthy_provider_leaves_general_conversation_fulfillable(self) -> None:
        self.monitor.record_success(provider="openai-compatible", now=T0)
        goal = RequestedGoal("자유 대화", required_capabilities=(GENERAL_CONVERSATION,))
        assessment = diagnose(
            goal, self.registry, runtime_observations=self._observations(T_SOON)
        )
        self.assertTrue(assessment.is_fulfillable_now)
        self.assertEqual(assessment.available_capabilities, (GENERAL_CONVERSATION,))
        self.assertEqual(assessment.blockers, ())

    def test_mission_read_survives_provider_offline(self) -> None:
        """The scenario the spec calls out: '현재 단타 연구 상태 알려줘' must
        stay fulfillable even when the LLM is down, because
        RESEARCH_MISSION_READ is not provider-backed."""
        self.monitor.record_failure(
            provider="openai-compatible", now=T0, error_type="ProviderUnavailableError"
        )
        goal = RequestedGoal("연구 상태", required_capabilities=(RESEARCH_MISSION_READ,))
        assessment = diagnose(
            goal, self.registry, runtime_observations=self._observations(T_SOON)
        )
        self.assertTrue(assessment.is_fulfillable_now)
        self.assertEqual(assessment.runtime_unavailable_capabilities, ())

    def test_forbidden_capability_stays_forbidden_regardless_of_provider_health(self) -> None:
        for outcome in ("healthy", "offline"):
            monitor = ProviderRuntimeMonitor()
            if outcome == "healthy":
                monitor.record_success(provider="openai-compatible", now=T0)
            else:
                monitor.record_failure(
                    provider="openai-compatible", now=T0, error_type="ProviderUnavailableError"
                )
            observations = observation_index(
                resolve_runtime_observations(self.registry, monitor, now=T_SOON)
            )
            goal = RequestedGoal("챔피언 승격", required_capabilities=(CHAMPION_PROMOTION,))
            assessment = diagnose(goal, self.registry, runtime_observations=observations)
            self.assertEqual(assessment.forbidden_capabilities, (CHAMPION_PROMOTION,))
            self.assertEqual(assessment.primary_blocker.kind, BlockerKind.FORBIDDEN_BY_SAFETY)
            self.assertIn("승인", assessment.recommended_next_step)

    def test_approval_required_stays_approval_required_regardless_of_provider_health(self) -> None:
        self.monitor.record_failure(
            provider="openai-compatible", now=T0, error_type="ProviderUnavailableError"
        )
        goal = RequestedGoal("연구 실행", required_capabilities=(RESEARCH_MISSION_RUN,))
        assessment = diagnose(
            goal, self.registry, runtime_observations=self._observations(T_SOON)
        )
        self.assertEqual(assessment.approval_required_capabilities, (RESEARCH_MISSION_RUN,))
        kinds = {b.kind for b in assessment.blockers}
        self.assertIn(BlockerKind.APPROVAL_REQUIRED, kinds)

    def test_missing_capability_is_a_capability_unavailable_blocker(self) -> None:
        goal = RequestedGoal("링크 열기", required_capabilities=(URL_FETCH,))
        assessment = diagnose(goal, self.registry, runtime_observations=self._observations(T0))
        self.assertEqual(assessment.missing_capabilities, (URL_FETCH,))
        self.assertEqual(assessment.primary_blocker.kind, BlockerKind.CAPABILITY_UNAVAILABLE)
        self.assertTrue(assessment.code_change_potentially_required)

    def test_missing_user_input_data_and_evidence_produce_typed_blockers(self) -> None:
        goal = RequestedGoal("분석", required_capabilities=(GENERAL_CONVERSATION,))
        self.monitor.record_success(provider="openai-compatible", now=T0)
        assessment = diagnose(
            goal,
            self.registry,
            runtime_observations=self._observations(T_SOON),
            missing_user_input=("대상 종목",),
            missing_data=("최근 체결 데이터",),
            missing_evidence=("외부 주장 출처",),
        )
        kinds = {b.kind for b in assessment.blockers}
        self.assertEqual(
            kinds,
            {
                BlockerKind.MISSING_USER_INPUT,
                BlockerKind.MISSING_DATA,
                BlockerKind.MISSING_EVIDENCE,
            },
        )
        self.assertFalse(assessment.is_fulfillable_now)

    def test_diagnose_without_observations_matches_registry_partition(self) -> None:
        """Back-compat: called with no runtime observations, diagnose is a
        superset of assess_from_registry and never invents a runtime block."""
        goal = RequestedGoal("자유 대화", required_capabilities=(GENERAL_CONVERSATION,))
        assessment = diagnose(goal, self.registry)
        self.assertTrue(assessment.is_fulfillable_now)
        self.assertEqual(assessment.available_capabilities, (GENERAL_CONVERSATION,))
        self.assertEqual(assessment.runtime_unavailable_capabilities, ())

    def test_llm_cannot_grant_a_capability_through_diagnose(self) -> None:
        """There is no code path by which model output reaches the registry
        or the monitor. A goal 'make TRADING_EXECUTION available' is just a
        FORBIDDEN capability requirement and stays blocked."""
        self.monitor.record_success(provider="openai-compatible", now=T0)
        goal = RequestedGoal(
            "TRADING_EXECUTION available 로 바꿔",
            required_capabilities=(TRADING_EXECUTION,),
        )
        assessment = diagnose(
            goal, self.registry, runtime_observations=self._observations(T_SOON)
        )
        self.assertEqual(assessment.forbidden_capabilities, (TRADING_EXECUTION,))
        self.assertFalse(assessment.is_fulfillable_now)
        self.assertNotIn(TRADING_EXECUTION, assessment.available_capabilities)


if __name__ == "__main__":
    unittest.main()
