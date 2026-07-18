import unittest

from gaon.runtime.agents import (
    AgentCapability,
    AgentDispatcher,
    AgentRegistry,
    AgentRequest,
    AgentStatus,
    CodingAgent,
    MemoryAgent,
    ResearchAgent,
    default_agent_registry,
)
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import ConfigurationError
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.executive_planner import AgentSelection, DeterministicExecutivePlanner, ExecutivePlan, ExecutiveRequest, RoutingDecision, ToolSelection
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.storage import RuntimeStateStore


class FailingAgent:
    name = "research_brain"
    capabilities = (AgentCapability.RESEARCH,)

    def execute(self, context):
        raise RuntimeError("hidden failure")


class AgentFrameworkTest(unittest.TestCase):
    def request(self, text: str = "research context") -> AgentRequest:
        return AgentRequest("agent-req", text, "actor:redacted", "2026-07-18T00:00:00Z")

    def plan(
        self,
        agent: AgentSelection = AgentSelection.RESEARCH_BRAIN,
        *,
        tools: tuple[ToolSelection, ...] = (ToolSelection.RESEARCH_PLANNER,),
        approval_required: bool = False,
        decision: RoutingDecision = RoutingDecision.RESEARCH,
    ) -> ExecutivePlan:
        if approval_required and ToolSelection.APPROVAL_WORKFLOW not in tools:
            tools = (*tools, ToolSelection.APPROVAL_WORKFLOW)
        return ExecutivePlan(
            "exec-plan:test",
            "agent-req",
            decision,
            (agent,),
            tools,
            approval_required,
            "unit test plan",
            "deterministic",
            "rule_based",
            "2026-07-18T00:00:00Z",
            "agent",
            "StrategyLab",
            "N/A",
            "N/A",
        )

    def test_agent_registration_duplicate_unknown_and_ordering(self) -> None:
        registry = AgentRegistry()
        registry.register(ResearchAgent())
        registry.register(MemoryAgent())

        self.assertEqual(registry.names(), ("learning_memory", "research_brain"))
        self.assertIn(AgentCapability.RESEARCH, registry.capabilities("research_brain"))
        with self.assertRaises(ConfigurationError):
            registry.register(ResearchAgent())
        with self.assertRaises(ConfigurationError):
            registry.get("missing")

    def test_deterministic_agent_execution_structured_result_and_metrics(self) -> None:
        metrics = MetricsCollector()
        result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig(), metrics=metrics).dispatch(self.plan(), self.request())

        self.assertEqual(result.agent_name, "research_brain")
        self.assertEqual(result.status, AgentStatus.SUCCEEDED)
        self.assertIn("research plan prepared", result.output)
        self.assertIsNone(result.error)
        self.assertIn("started_at", result.__dataclass_fields__)
        self.assertIn("gaon_agent_executions_total", metrics.snapshot().to_text())

    def test_capability_validation_failure_is_isolated(self) -> None:
        result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig()).dispatch(
            self.plan(AgentSelection.CODING_ASSISTANT, tools=(ToolSelection.MEMORY_RETRIEVAL,)),
            self.request(),
        )

        self.assertEqual(result.status, AgentStatus.FAILED)
        self.assertEqual(result.error, "ConfigurationError")

    def test_failing_agent_does_not_crash_runtime(self) -> None:
        registry = AgentRegistry()
        registry.register(FailingAgent())
        result = AgentDispatcher(registry, GaonRuntimeConfig()).dispatch(
            self.plan(),
            self.request(),
        )
        self.assertEqual(result.status, AgentStatus.FAILED)

    def test_approval_required_blocks_execution(self) -> None:
        metrics = MetricsCollector()
        result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig(), metrics=metrics).dispatch(
            self.plan(approval_required=True, decision=RoutingDecision.HUMAN_REVIEW),
            self.request("execute protected action"),
        )

        self.assertEqual(result.status, AgentStatus.REQUIRES_APPROVAL)
        self.assertIn("blocked", result.output)
        self.assertIn("gaon_agent_execution_blocked_total", metrics.snapshot().to_text())

    def test_event_emission_for_started_and_completed(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            dispatcher = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig(), event_store=SQLiteEventStore(store._connection))
            result = dispatcher.dispatch(self.plan(), self.request())
            events = SQLiteEventStore(store._connection).read_after()

            self.assertEqual(result.status, AgentStatus.SUCCEEDED)
            self.assertEqual({event.event_type for event in events}, {"AgentExecutionStarted", "AgentExecutionCompleted"})
        finally:
            store.close()

    def test_initial_agents_boundaries_and_free_only_defaults(self) -> None:
        config = GaonRuntimeConfig()
        self.assertTrue(config.free_only_mode)
        self.assertFalse(config.paid_provider_enabled)
        self.assertIn(AgentCapability.REPOSITORY_READ, CodingAgent().capabilities)
        self.assertEqual(MemoryAgent().capabilities, (AgentCapability.MEMORY_READ,))

    def test_executive_planner_plan_can_drive_dispatcher(self) -> None:
        executive_plan = DeterministicExecutivePlanner().plan(ExecutiveRequest("agent-req", "research evidence", "actor:redacted", "2026-07-18T00:00:00Z"))
        result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig()).dispatch(executive_plan, self.request("research evidence"))

        self.assertEqual(result.status, AgentStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
