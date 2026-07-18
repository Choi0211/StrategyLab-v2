"""Validated research planning for Gaon Research Brain."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from gaon.runtime.assistant_provider import AssistantProvider, AssistantRequest
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.event_store import DurableEvent
from gaon.runtime.intents import Intent
from gaon.runtime.metrics import MetricsCollector


class ResearchStepType(str, Enum):
    MEMORY_SEARCH = "memory_search"
    WEB_SEARCH = "web_search"
    RSS_FETCH = "rss_fetch"
    REPOSITORY_SEARCH = "repository_search"
    EVIDENCE_FILTER = "evidence_filter"
    CONTEXT_BUILD = "context_build"
    SYNTHESIS = "synthesis"
    KNOWLEDGE_PROPOSAL = "knowledge_proposal"
    REPORT_RENDER = "report_render"


ALLOWED_TOOLS = frozenset(step.value for step in ResearchStepType)
MAX_PLAN_STEPS = 20
MAX_PLAN_DEPTH = 8


@dataclass(frozen=True)
class ResearchRequest:
    request_id: str
    query: str
    actor_ref: str
    created_at: str
    free_only: bool = True


@dataclass(frozen=True)
class ResearchStep:
    step_id: str
    step_type: ResearchStepType
    tool_name: str
    depends_on: tuple[str, ...] = ()
    max_results: int = 5
    max_content_chars: int = 4000


@dataclass(frozen=True)
class ResearchPlan:
    plan_id: str
    request: ResearchRequest
    steps: tuple[ResearchStep, ...]
    version: int
    plan_hash: str
    lifecycle: str = "planned"


def deterministic_research_plan(request: ResearchRequest, *, metrics: MetricsCollector | None = None) -> ResearchPlan:
    steps = (
        ResearchStep("step:memory", ResearchStepType.MEMORY_SEARCH, "memory_search"),
        ResearchStep("step:evidence", ResearchStepType.EVIDENCE_FILTER, "evidence_filter", ("step:memory",)),
        ResearchStep("step:context", ResearchStepType.CONTEXT_BUILD, "context_build", ("step:evidence",)),
        ResearchStep("step:synthesis", ResearchStepType.SYNTHESIS, "synthesis", ("step:context",)),
        ResearchStep("step:proposal", ResearchStepType.KNOWLEDGE_PROPOSAL, "knowledge_proposal", ("step:synthesis",)),
        ResearchStep("step:report", ResearchStepType.REPORT_RENDER, "report_render", ("step:proposal",)),
    )
    plan = build_research_plan(request, steps, version=1)
    if metrics is not None:
        metrics.increment("gaon_research_plan_steps_total", component="planner")
    return plan


def provider_backed_research_plan(request: ResearchRequest, provider: AssistantProvider, config: GaonRuntimeConfig) -> ResearchPlan:
    if config.assistant_provider != "deterministic" and (request.free_only or not config.assistant_enabled):
        raise PermissionError("free-only mode forbids paid or disabled provider planning")
    response = provider.respond(AssistantRequest(request.query, Intent.SEARCH_MEMORY, request.actor_ref, request.request_id, request.created_at))
    payload = json.loads(response.text)
    steps = tuple(
        ResearchStep(
            step_id=str(item["step_id"]),
            step_type=ResearchStepType(str(item["step_type"])),
            tool_name=str(item["tool_name"]),
            depends_on=tuple(str(dep) for dep in item.get("depends_on", ())),
        )
        for item in payload.get("steps", ())
    )
    return build_research_plan(request, steps, version=int(payload.get("version", 1)))


def build_research_plan(request: ResearchRequest, steps: tuple[ResearchStep, ...], *, version: int) -> ResearchPlan:
    validate_research_plan_steps(steps)
    material = {
        "request_id": request.request_id,
        "query": request.query,
        "version": version,
        "steps": [
            {"step_id": step.step_id, "step_type": step.step_type.value, "tool_name": step.tool_name, "depends_on": step.depends_on}
            for step in steps
        ],
    }
    plan_hash = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ResearchPlan(f"plan:{request.request_id}:{plan_hash[:12]}", request, steps, version, plan_hash)


def validate_research_plan_steps(steps: tuple[ResearchStep, ...]) -> None:
    if not steps:
        raise ValueError("research plan requires at least one step")
    if len(steps) > MAX_PLAN_STEPS:
        raise ValueError("research plan exceeds maximum steps")
    ids = [step.step_id for step in steps]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate research step id")
    id_set = set(ids)
    for step in steps:
        if step.tool_name not in ALLOWED_TOOLS:
            raise ValueError(f"unknown research tool: {step.tool_name}")
        if len(step.depends_on) > MAX_PLAN_DEPTH:
            raise ValueError("research step exceeds dependency depth")
        missing = set(step.depends_on) - id_set
        if missing:
            raise ValueError("research step has unknown dependency")
    _reject_cycles(steps)


def plan_lifecycle_event(plan: ResearchPlan, *, appended_at: str) -> DurableEvent:
    return DurableEvent(
        event_id=f"event:research-plan:{plan.plan_id}",
        event_type="ResearchPlanCreated",
        occurred_at=appended_at,
        actor_ref=plan.request.actor_ref,
        correlation_id=plan.request.request_id,
        causation_id=None,
        scope="research",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
        payload={"plan_id": plan.plan_id, "plan_hash": plan.plan_hash, "steps": len(plan.steps)},
        evidence_refs=(),
        audit_refs=(),
        appended_at=appended_at,
    )


def _reject_cycles(steps: tuple[ResearchStep, ...]) -> None:
    graph = {step.step_id: set(step.depends_on) for step in steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise ValueError("research plan contains dependency cycle")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dep in graph[step_id]:
            visit(dep)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in graph:
        visit(step_id)
