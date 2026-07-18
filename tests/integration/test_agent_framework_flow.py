import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.runtime.agents import AgentDispatcher, AgentRequest, AgentStatus, default_agent_registry
from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.executive_planner import AgentSelection, DeterministicExecutivePlanner, ExecutivePlan, ExecutiveRequest, RoutingDecision, ToolSelection


class AgentFrameworkFlowTest(unittest.TestCase):
    def agent_request(self, text: str) -> AgentRequest:
        return AgentRequest("flow-req", text, "actor:redacted", "2026-07-18T00:00:00Z")

    def plan_for(self, agent: AgentSelection, decision: RoutingDecision, tools: tuple[ToolSelection, ...]) -> ExecutivePlan:
        return ExecutivePlan(
            "exec-plan:flow",
            "flow-req",
            decision,
            (agent,),
            tools,
            False,
            "integration flow",
            "deterministic",
            "rule_based",
            "2026-07-18T00:00:00Z",
            "agent",
            "StrategyLab",
            "N/A",
            "N/A",
        )

    def test_executive_planner_to_research_agent_result(self) -> None:
        plan = DeterministicExecutivePlanner().plan(ExecutiveRequest("flow-req", "research evidence", "actor:redacted", "2026-07-18T00:00:00Z"))
        result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig()).dispatch(plan, self.agent_request("research evidence"))

        self.assertEqual(result.status, AgentStatus.SUCCEEDED)
        self.assertEqual(result.agent_name, "research_brain")

    def test_research_coding_and_memory_agents_execute_deterministically(self) -> None:
        dispatcher = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig())

        research = dispatcher.dispatch(
            self.plan_for(AgentSelection.RESEARCH_BRAIN, RoutingDecision.RESEARCH, (ToolSelection.RESEARCH_PLANNER,)),
            self.agent_request("research context"),
        )
        coding = dispatcher.dispatch(
            self.plan_for(AgentSelection.CODING_ASSISTANT, RoutingDecision.RUNTIME, (ToolSelection.NOOP,)),
            self.agent_request("inspect repository shape"),
        )
        memory = dispatcher.dispatch(
            self.plan_for(AgentSelection.LEARNING_MEMORY, RoutingDecision.MEMORY, (ToolSelection.MEMORY_RETRIEVAL,)),
            self.agent_request("memory lookup"),
        )

        self.assertEqual(research.status, AgentStatus.SUCCEEDED)
        self.assertIn("no shell command", coding.output)
        self.assertIn("read-only", memory.output)

    def test_failed_agent_route_does_not_crash_runtime(self) -> None:
        result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig()).dispatch(
            self.plan_for(AgentSelection.RUNTIME_OPERATOR, RoutingDecision.RUNTIME, (ToolSelection.RUNTIME_STATUS,)),
            self.agent_request("runtime status"),
        )

        self.assertEqual(result.status, AgentStatus.FAILED)
        self.assertEqual(result.error, "ConfigurationError")

    def test_approval_required_plan_is_blocked_safely(self) -> None:
        plan = ExecutivePlan(
            "exec-plan:approval",
            "flow-req",
            RoutingDecision.HUMAN_REVIEW,
            (AgentSelection.RESEARCH_BRAIN,),
            (ToolSelection.RESEARCH_PLANNER, ToolSelection.APPROVAL_WORKFLOW),
            True,
            "approval required",
            "deterministic",
            "rule_based",
            "2026-07-18T00:00:00Z",
            "agent",
            "StrategyLab",
            "N/A",
            "N/A",
        )
        result = AgentDispatcher(default_agent_registry(), GaonRuntimeConfig()).dispatch(plan, self.agent_request("execute protected action"))

        self.assertEqual(result.status, AgentStatus.REQUIRES_APPROVAL)
        self.assertIn("approval", result.output)

    def test_cli_agent_run_smoke(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["agent-run", "--agent", "research", "--request", "research context"]), 0)
            self.assertEqual(cli_main(["agent-run", "--agent", "coding", "--request", "inspect code", "--json"]), 0)
            self.assertEqual(cli_main(["agent-run", "--agent", "memory", "--request", "memory lookup"]), 0)

        text = output.getvalue()
        self.assertIn("agent-run: agent=research_brain status=succeeded", text)
        self.assertIn('"agent_name":"coding_assistant"', text)
        self.assertIn("agent=learning_memory status=succeeded", text)


if __name__ == "__main__":
    unittest.main()
