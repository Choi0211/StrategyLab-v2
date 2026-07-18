"""Bounded multi-agent execution framework."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from gaon.adapters.trading import PaperTradingAdapter, TradingExecutionService, TradingIntent, TradingRiskPolicy, build_trading_request
from gaon.research.planning import ResearchRequest, deterministic_research_plan
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import ConfigurationError
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.executive_planner import AgentSelection, ExecutivePlan, RoutingDecision, ToolSelection
from gaon.runtime.metrics import MetricsCollector


class AgentCapability(str, Enum):
    RESEARCH = "research"
    REPOSITORY_READ = "repository_read"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE_PROPOSAL = "memory_write_proposal"
    REPORT_GENERATION = "report_generation"
    APPROVAL_REVIEW = "approval_review"
    TRADING_SIMULATION = "trading_simulation"


class AgentStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    REQUIRES_APPROVAL = "requires_approval"


@dataclass(frozen=True)
class AgentRequest:
    request_id: str
    text: str
    actor_ref: str
    created_at: str
    requested_capabilities: tuple[AgentCapability, ...] = ()

    def __post_init__(self) -> None:
        if not self.request_id or not self.text.strip() or not self.actor_ref or not self.created_at:
            raise ValueError("agent request requires id, text, actor, and timestamp")


@dataclass(frozen=True)
class AgentExecutionContext:
    plan: ExecutivePlan
    request: AgentRequest
    config: GaonRuntimeConfig
    correlation_id: str
    run_id: str | None = None
    dry_run: bool = True


@dataclass(frozen=True)
class AgentResult:
    agent_name: str
    status: AgentStatus
    output: str
    error: str | None
    metadata: dict[str, str]
    started_at: str
    completed_at: str


class Agent(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def capabilities(self) -> tuple[AgentCapability, ...]: ...
    def execute(self, context: AgentExecutionContext) -> AgentResult: ...


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        if not agent.name or agent.name.strip() != agent.name:
            raise ConfigurationError("agent name must be stable and trimmed")
        if agent.name in self._agents:
            raise ConfigurationError(f"duplicate agent registration: {agent.name}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise ConfigurationError(f"unknown agent: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents))

    def capabilities(self, name: str) -> tuple[AgentCapability, ...]:
        return self.get(name).capabilities


class AgentDispatcher:
    def __init__(
        self,
        registry: AgentRegistry,
        config: GaonRuntimeConfig,
        *,
        metrics: MetricsCollector | None = None,
        event_store: SQLiteEventStore | None = None,
    ) -> None:
        self._registry = registry
        self._config = config
        self._metrics = metrics or MetricsCollector()
        self._event_store = event_store

    def dispatch(self, plan: ExecutivePlan, request: AgentRequest) -> AgentResult:
        started_at = request.created_at
        if plan.approval_required or plan.routing_decision == RoutingDecision.HUMAN_REVIEW:
            result = _result(
                agent_name="dispatcher",
                status=AgentStatus.REQUIRES_APPROVAL,
                output="execution blocked until explicit approval",
                error=None,
                started_at=started_at,
                completed_at=started_at,
                metadata={"plan_id": plan.plan_id, "routing_decision": plan.routing_decision.value},
            )
            self._record(result, plan, request)
            self._metrics.increment("gaon_agent_execution_blocked_total", component="agent", agent=result.agent_name)
            return result
        if plan.routing_decision == RoutingDecision.UNSUPPORTED or not plan.agents:
            result = _result(
                agent_name="dispatcher",
                status=AgentStatus.BLOCKED,
                output="execution blocked because no supported agent route exists",
                error=None,
                started_at=started_at,
                completed_at=started_at,
                metadata={"plan_id": plan.plan_id, "routing_decision": plan.routing_decision.value},
            )
            self._record(result, plan, request)
            self._metrics.increment("gaon_agent_execution_blocked_total", component="agent", agent=result.agent_name)
            return result
        agent_name = plan.agents[0].value
        try:
            agent = self._registry.get(agent_name)
            required = _required_capabilities(plan, request)
            _validate_capabilities(agent, required)
            context = AgentExecutionContext(plan, request, self._config, correlation_id=plan.request_id, run_id=plan.plan_id)
            self._record(_started_result(agent.name, started_at, plan), plan, request, event_type="AgentExecutionStarted")
            result = agent.execute(context)
        except Exception as exc:  # noqa: BLE001 - one agent failure must not crash runtime.
            result = _result(
                agent_name=agent_name,
                status=AgentStatus.FAILED,
                output="agent execution failed safely",
                error=exc.__class__.__name__,
                started_at=started_at,
                completed_at=started_at,
                metadata={"plan_id": plan.plan_id, "routing_decision": plan.routing_decision.value},
            )
            self._metrics.increment("gaon_agent_execution_failures_total", component="agent", agent=_safe_metric_agent(agent_name))
            self._record(result, plan, request)
            return result
        if result.status == AgentStatus.SUCCEEDED:
            self._metrics.increment("gaon_agent_executions_total", component="agent", agent=_safe_metric_agent(result.agent_name))
        elif result.status in {AgentStatus.BLOCKED, AgentStatus.REQUIRES_APPROVAL}:
            self._metrics.increment("gaon_agent_execution_blocked_total", component="agent", agent=_safe_metric_agent(result.agent_name))
        else:
            self._metrics.increment("gaon_agent_execution_failures_total", component="agent", agent=_safe_metric_agent(result.agent_name))
        self._record(result, plan, request)
        return result

    def _record(self, result: AgentResult, plan: ExecutivePlan, request: AgentRequest, *, event_type: str | None = None) -> None:
        if self._event_store is None:
            return
        self._event_store.append(agent_execution_event(result, plan, request, event_type=event_type))


class ResearchAgent:
    name = AgentSelection.RESEARCH_BRAIN.value
    capabilities = (AgentCapability.RESEARCH, AgentCapability.REPORT_GENERATION)

    def execute(self, context: AgentExecutionContext) -> AgentResult:
        plan = deterministic_research_plan(
            ResearchRequest(
                request_id=f"agent:{context.request.request_id}",
                query=context.request.text,
                actor_ref=context.request.actor_ref,
                created_at=context.request.created_at,
            )
        )
        return _result(
            agent_name=self.name,
            status=AgentStatus.SUCCEEDED,
            output=f"research plan prepared: {len(plan.steps)} steps",
            error=None,
            started_at=context.request.created_at,
            completed_at=context.request.created_at,
            metadata={"plan_hash": plan.plan_hash, "dry_run": str(context.dry_run)},
        )


class CodingAgent:
    name = AgentSelection.CODING_ASSISTANT.value
    capabilities = (AgentCapability.REPOSITORY_READ, AgentCapability.REPORT_GENERATION)

    def execute(self, context: AgentExecutionContext) -> AgentResult:
        return _result(
            agent_name=self.name,
            status=AgentStatus.SUCCEEDED,
            output="coding request inspected; no shell command or file mutation executed",
            error=None,
            started_at=context.request.created_at,
            completed_at=context.request.created_at,
            metadata={"mode": "inspection_only"},
        )


class MemoryAgent:
    name = AgentSelection.LEARNING_MEMORY.value
    capabilities = (AgentCapability.MEMORY_READ,)

    def execute(self, context: AgentExecutionContext) -> AgentResult:
        return _result(
            agent_name=self.name,
            status=AgentStatus.SUCCEEDED,
            output="memory request inspected with read-only boundary; no knowledge promotion performed",
            error=None,
            started_at=context.request.created_at,
            completed_at=context.request.created_at,
            metadata={"mode": "read_only"},
        )


class TradingAgentPlaceholder:
    name = AgentSelection.TRADING_AGENT.value
    capabilities = (AgentCapability.TRADING_SIMULATION, AgentCapability.APPROVAL_REVIEW)

    def execute(self, context: AgentExecutionContext) -> AgentResult:
        intent = _trading_intent_from_text(context.request.text)
        if intent in {TradingIntent.LIVE_BUY, TradingIntent.LIVE_SELL}:
            return _result(
                agent_name=self.name,
                status=AgentStatus.REQUIRES_APPROVAL,
                output="live trading is not implemented in the public repository",
                error=None,
                started_at=context.request.created_at,
                completed_at=context.request.created_at,
                metadata={"mode": "live_trading_blocked", "intent": intent.value},
            )
        request = build_trading_request(
            f"agent-trading:{context.request.request_id}",
            intent,
            symbol=_trading_symbol_from_text(context.request.text),
            quantity=1.0 if intent in {TradingIntent.SIMULATE_BUY, TradingIntent.SIMULATE_SELL} else 0.0,
            price=1000.0 if intent in {TradingIntent.SIMULATE_BUY, TradingIntent.SIMULATE_SELL} else None,
            actor_ref=context.request.actor_ref,
            created_at=context.request.created_at,
            idempotency_key=context.request.request_id,
        )
        result = TradingExecutionService(PaperTradingAdapter(), TradingRiskPolicy()).execute(request)
        if result.status.value in {"rejected", "blocked"}:
            status = AgentStatus.BLOCKED
        elif result.status.value == "failed":
            status = AgentStatus.FAILED
        else:
            status = AgentStatus.SUCCEEDED
        return _result(
            agent_name=self.name,
            status=status,
            output=result.message,
            error=None,
            started_at=context.request.created_at,
            completed_at=context.request.created_at,
            metadata={"mode": "paper_simulation_only", "intent": intent.value, "trading_status": result.status.value},
        )


def default_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(ResearchAgent())
    registry.register(CodingAgent())
    registry.register(MemoryAgent())
    registry.register(TradingAgentPlaceholder())
    return registry


def agent_execution_event(result: AgentResult, plan: ExecutivePlan, request: AgentRequest, *, event_type: str | None = None) -> DurableEvent:
    resolved_type = event_type or {
        AgentStatus.SUCCEEDED: "AgentExecutionCompleted",
        AgentStatus.FAILED: "AgentExecutionFailed",
        AgentStatus.BLOCKED: "AgentExecutionBlocked",
        AgentStatus.REQUIRES_APPROVAL: "AgentExecutionBlocked",
    }[result.status]
    return DurableEvent(
        event_id=f"event:agent:{plan.plan_id}:{result.agent_name}:{resolved_type}",
        event_type=resolved_type,
        occurred_at=result.completed_at,
        actor_ref=request.actor_ref,
        correlation_id=plan.request_id,
        causation_id=plan.plan_id,
        scope=plan.scope,
        project=plan.project,
        strategy=plan.strategy,
        market=plan.market,
        payload={
            "agent_name": result.agent_name,
            "status": result.status.value,
            "plan_id": plan.plan_id,
            "routing_decision": plan.routing_decision.value,
            "error": result.error or "",
        },
        evidence_refs=(),
        audit_refs=(),
        appended_at=result.completed_at,
    )


def _required_capabilities(plan: ExecutivePlan, request: AgentRequest) -> tuple[AgentCapability, ...]:
    required = list(request.requested_capabilities)
    mapping = {
        ToolSelection.RESEARCH_PLANNER: AgentCapability.RESEARCH,
        ToolSelection.EVIDENCE_SEARCH: AgentCapability.RESEARCH,
        ToolSelection.KNOWLEDGE_PROPOSAL: AgentCapability.REPORT_GENERATION,
        ToolSelection.MEMORY_RETRIEVAL: AgentCapability.MEMORY_READ,
        ToolSelection.RUNTIME_STATUS: AgentCapability.REPOSITORY_READ,
        ToolSelection.TRADING_SIMULATION: AgentCapability.TRADING_SIMULATION,
        ToolSelection.APPROVAL_WORKFLOW: AgentCapability.APPROVAL_REVIEW,
    }
    for tool in plan.tools:
        capability = mapping.get(tool)
        if capability is not None and capability not in required:
            required.append(capability)
    return tuple(required)


def _validate_capabilities(agent: Agent, required: tuple[AgentCapability, ...]) -> None:
    missing = tuple(capability for capability in required if capability not in agent.capabilities)
    if missing:
        raise ConfigurationError(f"agent {agent.name} lacks required capabilities")


def _started_result(agent_name: str, started_at: str, plan: ExecutivePlan) -> AgentResult:
    return _result(
        agent_name=agent_name,
        status=AgentStatus.SUCCEEDED,
        output="agent execution started",
        error=None,
        started_at=started_at,
        completed_at=started_at,
        metadata={"plan_id": plan.plan_id},
    )


def _result(
    *,
    agent_name: str,
    status: AgentStatus,
    output: str,
    error: str | None,
    started_at: str,
    completed_at: str,
    metadata: dict[str, str],
) -> AgentResult:
    return AgentResult(agent_name, status, output, error, dict(sorted(metadata.items())), started_at, completed_at)


def _safe_metric_agent(value: str) -> str:
    return value.replace("-", "_")


def _trading_intent_from_text(text: str) -> TradingIntent:
    lower = text.lower()
    if "live" in lower or "real order" in lower:
        return TradingIntent.LIVE_BUY if "buy" in lower else TradingIntent.LIVE_SELL
    if "cancel" in lower:
        return TradingIntent.CANCEL_SIMULATED_ORDER
    if "sell" in lower or "매도" in lower:
        return TradingIntent.SIMULATE_SELL
    if "buy" in lower or "매수" in lower:
        return TradingIntent.SIMULATE_BUY
    return TradingIntent.ANALYZE


def _trading_symbol_from_text(text: str) -> str:
    for token in text.replace(",", " ").split():
        cleaned = token.strip().upper()
        if cleaned.isalnum() and 2 <= len(cleaned) <= 12:
            return cleaned
    return "PAPER"
