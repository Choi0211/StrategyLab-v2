"""Safe conversational agent planner."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sqlite3
from uuid import uuid4

from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest
from gaon.runtime.serialization import dumps_json, loads_json


class AgentPlanStepType(str, Enum):
    READ_TOOL = "read_tool"
    CONTEXT_LOOKUP = "context_lookup"
    SYNTHESIZE = "synthesize"
    REQUIRES_HUMAN_APPROVAL = "requires_human_approval"


class AgentPlanStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    FAILED = "failed"
    REQUIRES_HUMAN_APPROVAL = "requires_human_approval"


@dataclass(frozen=True)
class AgentPlanStep:
    step_id: str
    step_type: AgentPlanStepType
    tool_name: str | None = None
    arguments: dict[str, object] | None = None
    reason: str = ""

    def to_json(self) -> dict[str, object]:
        return {"step_id": self.step_id, "step_type": self.step_type.value, "tool_name": self.tool_name, "arguments": self.arguments or {}, "reason": self.reason}


@dataclass(frozen=True)
class AgentPlan:
    plan_id: str
    request_text: str
    steps: tuple[AgentPlanStep, ...]
    status: AgentPlanStatus
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {"plan_id": self.plan_id, "request_text": self.request_text, "steps": [step.to_json() for step in self.steps], "status": self.status.value, "created_at": self.created_at}

    def with_status(self, status: AgentPlanStatus) -> "AgentPlan":
        return AgentPlan(self.plan_id, self.request_text, self.steps, status, self.created_at)


@dataclass(frozen=True)
class AgentPlanExecutionResult:
    plan_id: str
    status: AgentPlanStatus
    outputs: tuple[dict[str, object], ...]
    message: str


class AgentPlanPolicy:
    ALLOWED_TOOLS = {"runtime_status", "champion_status", "v5_pipeline_history", "web_search", "news_search", "market_data", "exchange_rate"}

    def __init__(self, *, max_steps: int = 5) -> None:
        self.max_steps = max_steps

    def validate(self, plan: AgentPlan) -> AgentPlanStatus:
        if len(plan.steps) > self.max_steps:
            return AgentPlanStatus.DENIED
        for step in plan.steps:
            if step.step_type not in {AgentPlanStepType.READ_TOOL, AgentPlanStepType.CONTEXT_LOOKUP, AgentPlanStepType.SYNTHESIZE, AgentPlanStepType.REQUIRES_HUMAN_APPROVAL}:
                return AgentPlanStatus.DENIED
            if step.tool_name and step.tool_name not in self.ALLOWED_TOOLS:
                return AgentPlanStatus.DENIED
        if any(step.step_type is AgentPlanStepType.REQUIRES_HUMAN_APPROVAL for step in plan.steps):
            return AgentPlanStatus.REQUIRES_HUMAN_APPROVAL
        return AgentPlanStatus.CREATED


class AgentPlanner:
    def plan(self, request_text: str, *, created_at: str) -> AgentPlan:
        lowered = request_text.casefold()
        if any(token in lowered for token in ("deploy", "approve", "promotion", "order", "trade", "buy", "sell", "배포", "승인", "주문", "매수", "매도", "諛고룷", "?뱀씤")):
            return AgentPlan(f"agent-plan:{uuid4().hex}", request_text, (AgentPlanStep("step-1", AgentPlanStepType.REQUIRES_HUMAN_APPROVAL, reason="approval boundary"),), AgentPlanStatus.REQUIRES_HUMAN_APPROVAL, created_at)
        steps: list[AgentPlanStep] = []
        if any(token in lowered for token in ("champion", "챔피언")):
            steps.append(AgentPlanStep("step-1", AgentPlanStepType.READ_TOOL, "champion_status", {"slot": "default"}, "read champion state"))
        if any(token in lowered for token in ("v5", "pipeline", "파이프라인")):
            steps.append(AgentPlanStep(f"step-{len(steps)+1}", AgentPlanStepType.READ_TOOL, "v5_pipeline_history", {"limit": 5}, "read v5 pipeline history"))
        if any(token in lowered for token in ("market", "news", "web", "research", "search", "external", "시장", "뉴스", "검색", "조사")):
            steps.append(AgentPlanStep(f"step-{len(steps)+1}", AgentPlanStepType.READ_TOOL, "market_data", {"symbol": "KOSPI"}, "read configured market data"))
            steps.append(AgentPlanStep(f"step-{len(steps)+1}", AgentPlanStepType.READ_TOOL, "exchange_rate", {"base": "USD", "quote": "KRW"}, "read configured FX data"))
            steps.append(AgentPlanStep(f"step-{len(steps)+1}", AgentPlanStepType.READ_TOOL, "news_search", {"query": request_text, "max_results": 3}, "read external news citations"))
        if not steps:
            routed = route_read_only_tool(request_text)
            if routed:
                args = {"slot": "default"} if routed == "champion_status" else {"limit": 5} if routed == "v5_pipeline_history" else {}
                steps.append(AgentPlanStep("step-1", AgentPlanStepType.READ_TOOL, routed, args, "deterministic read-only route"))
        steps.append(AgentPlanStep(f"step-{len(steps)+1}", AgentPlanStepType.SYNTHESIZE, reason="summarize bounded results"))
        return AgentPlan(f"agent-plan:{uuid4().hex}", request_text, tuple(steps), AgentPlanStatus.CREATED, created_at)


class AgentPlanExecutor:
    def __init__(self, tool_executor: SafeToolExecutor, policy: AgentPlanPolicy | None = None) -> None:
        self._tool_executor = tool_executor
        self._policy = policy or AgentPlanPolicy()

    def execute(self, plan: AgentPlan, *, actor_ref: str, now: str) -> AgentPlanExecutionResult:
        status = self._policy.validate(plan)
        if status is AgentPlanStatus.DENIED:
            return AgentPlanExecutionResult(plan.plan_id, AgentPlanStatus.DENIED, (), "plan denied by policy")
        if status is AgentPlanStatus.REQUIRES_HUMAN_APPROVAL:
            return AgentPlanExecutionResult(plan.plan_id, status, (), "human approval required; execution stopped")
        outputs: list[dict[str, object]] = []
        for step in plan.steps:
            if step.step_type is AgentPlanStepType.READ_TOOL and step.tool_name:
                result = self._tool_executor.execute(ToolRequest(step.tool_name, step.arguments or {}, actor_ref, now))
                outputs.append({"tool_name": result.tool_name, "status": result.status, "output": result.output})
                if result.status != "success":
                    return AgentPlanExecutionResult(plan.plan_id, AgentPlanStatus.DENIED, tuple(outputs), "tool execution denied")
        return AgentPlanExecutionResult(plan.plan_id, AgentPlanStatus.COMPLETED, tuple(outputs), "plan completed")


class SQLiteAgentPlanRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put(self, plan: AgentPlan, *, updated_at: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO agent_plans(plan_id, status, request_text, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(plan_id) DO UPDATE SET status=excluded.status, payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (plan.plan_id, plan.status.value, plan.request_text, dumps_json(plan.to_json()), plan.created_at, updated_at),
            )

    def list(self) -> tuple[AgentPlan, ...]:
        rows = self._connection.execute("SELECT payload_json FROM agent_plans ORDER BY updated_at, plan_id").fetchall()
        return tuple(_plan_from_json(loads_json(str(row[0]))) for row in rows)


def _plan_from_json(payload: dict[str, object]) -> AgentPlan:
    steps = tuple(AgentPlanStep(str(step["step_id"]), AgentPlanStepType(str(step["step_type"])), str(step["tool_name"]) if step.get("tool_name") else None, dict(step.get("arguments", {})), str(step.get("reason", ""))) for step in payload.get("steps", []))  # type: ignore[union-attr]
    return AgentPlan(str(payload["plan_id"]), str(payload["request_text"]), steps, AgentPlanStatus(str(payload["status"])), str(payload["created_at"]))
