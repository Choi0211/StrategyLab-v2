import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantRequest, ProviderCapabilities, ProviderHealth
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import ConfigurationError
from gaon.runtime.executive_planner import (
    AgentSelection,
    DeterministicExecutivePlanner,
    ExecutivePlan,
    ExecutiveRequest,
    ProviderBackedExecutivePlanner,
    RoutingDecision,
    ToolSelection,
    executive_plan_event,
)
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.provider_registry import AssistantProviderRegistry, ProviderRegistration


class JsonPlanningProvider:
    def __init__(self, *, supports_network: bool = False, deterministic: bool = True, text: str | None = None) -> None:
        self._capabilities = ProviderCapabilities("json-planner", "fixture", supports_network, deterministic, 500)
        self._text = text or (
            '{"routing_decision":"research","agents":["research_brain"],'
            '"tools":["research_planner","evidence_search"],'
            '"approval_required":false,"reason":"provider selected research route"}'
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def health(self) -> ProviderHealth:
        return ProviderHealth("json-planner", True)

    def respond(self, request: AssistantRequest) -> AssistantProviderResponse:
        return AssistantProviderResponse(self._text, provider_name="json-planner", model="fixture")


class ExecutivePlannerTest(unittest.TestCase):
    def request(self, text: str = "ORB 전략 연구해줘") -> ExecutiveRequest:
        return ExecutiveRequest("req-1", text, "actor:redacted", "2026-07-18T00:00:00Z")

    def registry(self, provider: JsonPlanningProvider) -> AssistantProviderRegistry:
        registry = AssistantProviderRegistry()
        registry.register(ProviderRegistration("json", lambda _: provider, supports_network=provider.capabilities.supports_network, deterministic=provider.capabilities.deterministic))
        return registry

    def test_deterministic_research_routing_and_json_round_trip(self) -> None:
        metrics = MetricsCollector()
        plan = DeterministicExecutivePlanner(metrics=metrics).plan(self.request())
        restored = ExecutivePlan.from_json(plan.to_json())

        self.assertEqual(plan.routing_decision, RoutingDecision.RESEARCH)
        self.assertIn(AgentSelection.RESEARCH_BRAIN, plan.agents)
        self.assertIn(ToolSelection.EVIDENCE_SEARCH, plan.tools)
        self.assertFalse(plan.approval_required)
        self.assertEqual(restored, plan)
        self.assertIn("gaon_executive_plans_total", metrics.snapshot().to_text())

    def test_memory_runtime_and_unsupported_routes(self) -> None:
        planner = DeterministicExecutivePlanner()

        self.assertEqual(planner.plan(self.request("지난 연구 기억 검색해줘")).routing_decision, RoutingDecision.MEMORY)
        self.assertEqual(planner.plan(self.request("runtime status 알려줘")).routing_decision, RoutingDecision.RUNTIME)
        self.assertEqual(planner.plan(self.request("무작위 농담")).routing_decision, RoutingDecision.UNSUPPORTED)

    def test_approval_required_flag_for_execution_capable_request(self) -> None:
        plan = DeterministicExecutivePlanner().plan(self.request("삼성전자 매수 주문 실행해줘"))

        self.assertEqual(plan.routing_decision, RoutingDecision.HUMAN_REVIEW)
        self.assertTrue(plan.approval_required)
        self.assertIn(AgentSelection.HUMAN_REVIEWER, plan.agents)
        self.assertIn(ToolSelection.APPROVAL_WORKFLOW, plan.tools)

    def test_provider_backed_planner_uses_registry_and_validates_output(self) -> None:
        config = GaonRuntimeConfig(assistant_provider="json")
        plan = ProviderBackedExecutivePlanner(config, registry=self.registry(JsonPlanningProvider())).plan(self.request())

        self.assertEqual(plan.routing_decision, RoutingDecision.RESEARCH)
        self.assertEqual(plan.provider, "json")
        self.assertEqual(plan.route, "provider")

        bad_provider = JsonPlanningProvider(text="not-json")
        with self.assertRaises(ConfigurationError):
            ProviderBackedExecutivePlanner(config, registry=self.registry(bad_provider)).plan(self.request())

    def test_free_only_rejects_network_or_paid_provider(self) -> None:
        config = GaonRuntimeConfig(assistant_provider="json")
        provider = JsonPlanningProvider(supports_network=True, deterministic=False)

        with self.assertRaises(ConfigurationError):
            ProviderBackedExecutivePlanner(config, registry=self.registry(provider)).plan(self.request())

    def test_provider_cannot_clear_approval_required_for_risky_request(self) -> None:
        config = GaonRuntimeConfig(assistant_provider="json")
        plan = ProviderBackedExecutivePlanner(config, registry=self.registry(JsonPlanningProvider())).plan(self.request("정책 변경 실행해줘"))

        self.assertEqual(plan.routing_decision, RoutingDecision.HUMAN_REVIEW)
        self.assertTrue(plan.approval_required)
        self.assertIn(ToolSelection.APPROVAL_WORKFLOW, plan.tools)

    def test_event_store_payload_is_bounded_and_redacted(self) -> None:
        request = self.request()
        plan = DeterministicExecutivePlanner().plan(request)
        event = executive_plan_event(plan, actor_ref=request.actor_ref, appended_at=request.created_at)

        self.assertEqual(event.event_type, "ExecutivePlanCreated")
        self.assertEqual(event.scope, "executive")
        self.assertEqual(event.payload["approval_required"], False)
        self.assertNotIn("actor:redacted", str(event.payload))


if __name__ == "__main__":
    unittest.main()
