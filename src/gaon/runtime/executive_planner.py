"""Executive planning and routing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Protocol

from gaon.runtime.assistant_provider import AssistantRequest
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import ConfigurationError
from gaon.runtime.event_store import DurableEvent
from gaon.runtime.intents import Intent
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.provider_registry import AssistantProviderRegistry, default_provider_registry
from gaon.runtime.serialization import dumps_json, loads_json

EXECUTIVE_PLAN_SCHEMA_VERSION = 1
MAX_REQUEST_CHARS = 1000
MAX_AGENTS = 4
MAX_TOOLS = 6


class RoutingDecision(str, Enum):
    RESEARCH = "research"
    MEMORY = "memory"
    RUNTIME = "runtime"
    TRADING = "trading"
    HUMAN_REVIEW = "human_review"
    UNSUPPORTED = "unsupported"


class AgentSelection(str, Enum):
    RESEARCH_BRAIN = "research_brain"
    CODING_ASSISTANT = "coding_assistant"
    LEARNING_MEMORY = "learning_memory"
    RUNTIME_OPERATOR = "runtime_operator"
    TRADING_AGENT = "trading_agent"
    HUMAN_REVIEWER = "human_reviewer"


class ToolSelection(str, Enum):
    RESEARCH_PLANNER = "research_planner"
    EVIDENCE_SEARCH = "evidence_search"
    KNOWLEDGE_PROPOSAL = "knowledge_proposal"
    MEMORY_RETRIEVAL = "memory_retrieval"
    RUNTIME_STATUS = "runtime_status"
    TRADING_SIMULATION = "trading_simulation"
    BACKTEST_ADAPTER = "backtest_adapter"
    VALIDATION_ENGINE = "validation_engine"
    APPROVAL_WORKFLOW = "approval_workflow"
    NOOP = "noop"


@dataclass(frozen=True)
class ExecutiveRequest:
    request_id: str
    text: str
    actor_ref: str
    created_at: str
    scope: str = "executive"
    project: str = "StrategyLab"
    strategy: str = "N/A"
    market: str = "N/A"
    free_only: bool = True

    def __post_init__(self) -> None:
        if not self.request_id or not self.actor_ref or not self.created_at:
            raise ValueError("executive request requires id, actor, and timestamp")
        if not self.text.strip():
            raise ValueError("executive request text is required")
        if len(self.text) > MAX_REQUEST_CHARS:
            raise ValueError("executive request text is too long")


@dataclass(frozen=True)
class ExecutivePlan:
    plan_id: str
    request_id: str
    routing_decision: RoutingDecision
    agents: tuple[AgentSelection, ...]
    tools: tuple[ToolSelection, ...]
    approval_required: bool
    reason: str
    provider: str
    route: str
    created_at: str
    scope: str
    project: str
    strategy: str
    market: str
    schema_version: int = EXECUTIVE_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTIVE_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported executive plan schema version")
        if not self.plan_id or not self.request_id or not self.reason.strip():
            raise ValueError("executive plan requires id, request id, and reason")
        if len(self.agents) > MAX_AGENTS or len(self.tools) > MAX_TOOLS:
            raise ValueError("executive plan selections are too large")
        if self.approval_required and ToolSelection.APPROVAL_WORKFLOW not in self.tools:
            raise ValueError("approval-required plan must include approval workflow")

    def to_json(self) -> str:
        return dumps_json(
            {
                "schema_version": self.schema_version,
                "plan_id": self.plan_id,
                "request_id": self.request_id,
                "routing_decision": self.routing_decision.value,
                "agents": [agent.value for agent in self.agents],
                "tools": [tool.value for tool in self.tools],
                "approval_required": self.approval_required,
                "reason": self.reason,
                "provider": self.provider,
                "route": self.route,
                "created_at": self.created_at,
                "scope": self.scope,
                "project": self.project,
                "strategy": self.strategy,
                "market": self.market,
            }
        )

    @classmethod
    def from_json(cls, value: str) -> "ExecutivePlan":
        payload = loads_json(value)
        if payload.get("schema_version") != EXECUTIVE_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported executive plan schema version")
        return cls(
            plan_id=str(payload["plan_id"]),
            request_id=str(payload["request_id"]),
            routing_decision=RoutingDecision(str(payload["routing_decision"])),
            agents=tuple(AgentSelection(str(agent)) for agent in payload["agents"]),  # type: ignore[index]
            tools=tuple(ToolSelection(str(tool)) for tool in payload["tools"]),  # type: ignore[index]
            approval_required=bool(payload["approval_required"]),
            reason=str(payload["reason"]),
            provider=str(payload["provider"]),
            route=str(payload["route"]),
            created_at=str(payload["created_at"]),
            scope=str(payload["scope"]),
            project=str(payload["project"]),
            strategy=str(payload["strategy"]),
            market=str(payload["market"]),
        )


class ExecutivePlanner(Protocol):
    def plan(self, request: ExecutiveRequest) -> ExecutivePlan: ...


class DeterministicExecutivePlanner:
    def __init__(self, *, metrics: MetricsCollector | None = None) -> None:
        self._metrics = metrics or MetricsCollector()

    def plan(self, request: ExecutiveRequest) -> ExecutivePlan:
        plan = _deterministic_plan(request, provider="deterministic", route="rule_based")
        self._metrics.increment("gaon_executive_plans_total", component="executive", route=plan.route)
        return plan


class ProviderBackedExecutivePlanner:
    def __init__(
        self,
        config: GaonRuntimeConfig,
        *,
        registry: AssistantProviderRegistry | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._config = config
        self._registry = registry or default_provider_registry()
        self._metrics = metrics or MetricsCollector()

    def plan(self, request: ExecutiveRequest) -> ExecutivePlan:
        route = self._registry.route(self._config)
        capabilities = route.provider.capabilities
        if (request.free_only or self._config.free_only_mode) and (capabilities.supports_network or not capabilities.deterministic):
            raise ConfigurationError("executive planner free-only mode forbids paid or network provider routing")
        if capabilities.supports_network and not self._config.paid_provider_enabled:
            raise ConfigurationError("paid provider routing requires GAON_PAID_PROVIDER_ENABLED=true")
        response = route.provider.respond(
            AssistantRequest(
                text=request.text,
                intent=Intent.UNKNOWN,
                user_id=request.actor_ref,
                conversation_id=request.request_id,
                received_at=request.created_at,
                prompt="Return an executive routing plan as bounded JSON.",
            )
        )
        plan = _plan_from_provider_json(request, response.text, provider=route.selected_name, route="provider_fallback" if route.fallback_used else "provider")
        self._metrics.increment("gaon_executive_plans_total", component="executive", route=plan.route)
        return plan


def executive_plan_event(plan: ExecutivePlan, *, actor_ref: str, appended_at: str) -> DurableEvent:
    return DurableEvent(
        event_id=f"event:executive-plan:{plan.plan_id}",
        event_type="ExecutivePlanCreated",
        occurred_at=plan.created_at,
        actor_ref=actor_ref,
        correlation_id=plan.request_id,
        causation_id=None,
        scope=plan.scope,
        project=plan.project,
        strategy=plan.strategy,
        market=plan.market,
        payload={
            "plan_id": plan.plan_id,
            "routing_decision": plan.routing_decision.value,
            "agents": [agent.value for agent in plan.agents],
            "tools": [tool.value for tool in plan.tools],
            "approval_required": plan.approval_required,
            "provider": plan.provider,
            "route": plan.route,
        },
        evidence_refs=(),
        audit_refs=(),
        appended_at=appended_at,
    )


def _deterministic_plan(request: ExecutiveRequest, *, provider: str, route: str) -> ExecutivePlan:
    text = request.text.lower()
    approval_required = _requires_approval(text)
    if _is_validation_request(text):
        decision = RoutingDecision.RESEARCH
        agents = (AgentSelection.RESEARCH_BRAIN,)
        tools = (ToolSelection.BACKTEST_ADAPTER, ToolSelection.VALIDATION_ENGINE)
        reason = "route to deterministic validation engine boundary"
    elif _is_backtest_request(text):
        decision = RoutingDecision.RESEARCH
        agents = (AgentSelection.RESEARCH_BRAIN,)
        tools = (ToolSelection.RESEARCH_PLANNER, ToolSelection.BACKTEST_ADAPTER)
        reason = "route to safe v1 backtest adapter boundary"
    elif _is_trading_simulation(text):
        decision = RoutingDecision.TRADING
        agents = (AgentSelection.TRADING_AGENT,)
        tools = (ToolSelection.TRADING_SIMULATION,)
        reason = "route to paper trading simulation boundary"
    elif any(token in text for token in ("기억", "memory", "지난 연구", "검색")):
        decision = RoutingDecision.MEMORY
        agents = (AgentSelection.LEARNING_MEMORY,)
        tools = (ToolSelection.MEMORY_RETRIEVAL,)
        reason = "route to read-only memory retrieval"
    elif any(token in text for token in ("상태", "status", "health", "metrics")):
        decision = RoutingDecision.RUNTIME
        agents = (AgentSelection.RUNTIME_OPERATOR,)
        tools = (ToolSelection.RUNTIME_STATUS,)
        reason = "route to runtime status inspection"
    elif any(token in text for token in ("연구", "research", "분석", "evidence", "strategy", "전략")):
        decision = RoutingDecision.RESEARCH
        agents = (AgentSelection.RESEARCH_BRAIN,)
        tools = (ToolSelection.RESEARCH_PLANNER, ToolSelection.EVIDENCE_SEARCH, ToolSelection.KNOWLEDGE_PROPOSAL)
        reason = "route to evidence-backed research planning"
    else:
        decision = RoutingDecision.UNSUPPORTED
        agents = (AgentSelection.HUMAN_REVIEWER,)
        tools = (ToolSelection.NOOP,)
        reason = "request is not supported by Sprint 36 execution boundaries"
    if approval_required:
        decision = RoutingDecision.HUMAN_REVIEW
        agents = _append_unique(agents, AgentSelection.HUMAN_REVIEWER)
        tools = _append_unique(tools, ToolSelection.APPROVAL_WORKFLOW)
        reason = f"{reason}; approval required before any execution-capable future step"
    return ExecutivePlan(
        plan_id=f"exec-plan:{request.request_id}",
        request_id=request.request_id,
        routing_decision=decision,
        agents=agents,
        tools=tools,
        approval_required=approval_required,
        reason=reason,
        provider=provider,
        route=route,
        created_at=request.created_at,
        scope=request.scope,
        project=request.project,
        strategy=request.strategy,
        market=request.market,
    )


def _plan_from_provider_json(request: ExecutiveRequest, value: str, *, provider: str, route: str) -> ExecutivePlan:
    try:
        payload = json.loads(value)
        decision = RoutingDecision(str(payload["routing_decision"]))
        agents = tuple(AgentSelection(str(agent)) for agent in payload["agents"])
        tools = tuple(ToolSelection(str(tool)) for tool in payload["tools"])
        approval_required = bool(payload["approval_required"])
        reason = str(payload["reason"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConfigurationError("provider returned invalid executive plan JSON") from exc
    if _requires_approval(request.text.lower()):
        approval_required = True
        decision = RoutingDecision.HUMAN_REVIEW
        agents = _append_unique(agents, AgentSelection.HUMAN_REVIEWER)
        tools = _append_unique(tools, ToolSelection.APPROVAL_WORKFLOW)
    return ExecutivePlan(
        plan_id=f"exec-plan:{request.request_id}",
        request_id=request.request_id,
        routing_decision=decision,
        agents=agents,
        tools=tools,
        approval_required=approval_required,
        reason=reason,
        provider=provider,
        route=route,
        created_at=request.created_at,
        scope=request.scope,
        project=request.project,
        strategy=request.strategy,
        market=request.market,
    )


def _requires_approval(text: str) -> bool:
    if _is_trading_simulation(text):
        return False
    risky = ("매수", "매도", "주문", "실행", "approve", "approval", "trade", "trading", "execute", "delete", "policy", "live buy", "live sell", "real order")
    return any(token in text for token in risky)


def _is_trading_simulation(text: str) -> bool:
    simulation_tokens = ("simulate", "simulation", "paper", "paper-trade", "paper trade", "모의", "시뮬")
    trading_tokens = ("buy", "sell", "trade", "trading", "order", "portfolio", "position", "account", "cancel", "매수", "매도", "주문", "계좌", "포지션")
    return any(token in text for token in simulation_tokens) and any(token in text for token in trading_tokens)


def _is_backtest_request(text: str) -> bool:
    return any(token in text for token in ("backtest", "백테스트", "walk-forward", "simulation result"))


def _is_validation_request(text: str) -> bool:
    return any(token in text for token in ("validate", "validation", "robust", "robustness", "검증", "validation report"))


def _append_unique(items: tuple, item):
    return items if item in items else (*items, item)
