import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantRequest, ProviderCapabilities, ProviderHealth
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.metrics import MetricsCollector
from gaon.research.planning import (
    MAX_PLAN_STEPS,
    ResearchRequest,
    ResearchStep,
    ResearchStepType,
    deterministic_research_plan,
    plan_lifecycle_event,
    provider_backed_research_plan,
    validate_research_plan_steps,
)


class JsonProvider:
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake", "json", False, True, 1000)

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake", True)

    def respond(self, request: AssistantRequest) -> AssistantProviderResponse:
        return AssistantProviderResponse(
            '{"version":1,"steps":[{"step_id":"s1","step_type":"memory_search","tool_name":"memory_search","depends_on":[]}]}',
            provider_name="fake",
        )


class BadProvider(JsonProvider):
    def respond(self, request: AssistantRequest) -> AssistantProviderResponse:
        return AssistantProviderResponse('{"version":1,"steps":[{"step_id":"s1","step_type":"bad","tool_name":"bad"}]}')


class ResearchPlanningTest(unittest.TestCase):
    def request(self) -> ResearchRequest:
        return ResearchRequest("req-1", "ORB 전략 근거 조사", "actor:redacted", "2026-07-18T00:00:00Z")

    def test_deterministic_plan_stability(self) -> None:
        first = deterministic_research_plan(self.request())
        second = deterministic_research_plan(self.request())

        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertEqual(first.plan_id, second.plan_id)

    def test_cycle_unknown_tool_and_max_step_rejection(self) -> None:
        with self.assertRaises(ValueError):
            validate_research_plan_steps(
                (
                    ResearchStep("a", ResearchStepType.MEMORY_SEARCH, "memory_search", ("b",)),
                    ResearchStep("b", ResearchStepType.SYNTHESIS, "synthesis", ("a",)),
                )
            )
        with self.assertRaises(ValueError):
            validate_research_plan_steps((ResearchStep("a", ResearchStepType.MEMORY_SEARCH, "unregistered_tool"),))
        with self.assertRaises(ValueError):
            validate_research_plan_steps(tuple(ResearchStep(f"s{i}", ResearchStepType.MEMORY_SEARCH, "memory_search") for i in range(MAX_PLAN_STEPS + 1)))

    def test_provider_planner_free_only_and_invalid_output(self) -> None:
        with self.assertRaises(PermissionError):
            provider_backed_research_plan(self.request(), JsonProvider(), GaonRuntimeConfig(assistant_provider="openai-compatible"))
        plan = provider_backed_research_plan(
            ResearchRequest("req-2", "query", "actor:redacted", "2026-07-18T00:00:00Z", free_only=False),
            JsonProvider(),
            GaonRuntimeConfig(assistant_provider="deterministic"),
        )
        self.assertEqual(len(plan.steps), 1)
        with self.assertRaises(ValueError):
            provider_backed_research_plan(self.request(), BadProvider(), GaonRuntimeConfig())

    def test_plan_event_and_metric(self) -> None:
        metrics = MetricsCollector()
        plan = deterministic_research_plan(self.request(), metrics=metrics)
        event = plan_lifecycle_event(plan, appended_at="2026-07-18T00:00:00Z")

        self.assertEqual(event.event_type, "ResearchPlanCreated")
        self.assertIn("gaon_research_plan_steps_total", metrics.snapshot().to_text())


if __name__ == "__main__":
    unittest.main()
