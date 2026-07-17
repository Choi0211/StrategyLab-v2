"""Deterministic research request planner."""

from __future__ import annotations

import hashlib

from gaon.research.tasks import ResearchExecutionPlan, ResearchProposal, ResearchRequest


def plan_research_request(request: ResearchRequest) -> ResearchProposal:
    digest = hashlib.sha256(f"{request.request_id}:{request.text}".encode("utf-8")).hexdigest()[:12]
    goal = request.text.strip()
    plan = ResearchExecutionPlan(
        plan_id=f"plan:{digest}",
        goal=goal,
        scope="strategy-research",
        hypothesis=f"Research request can be evaluated safely: {goal}",
        required_data=("approved fixture data", "Learning Memory context"),
        validation_method="dry-run planning review before any execution",
        risks=("data unavailable", "overfitting", "unsupported execution request"),
        expected_artifacts=("research proposal", "approval request", "dry-run summary"),
        approval_required=True,
    )
    return ResearchProposal(f"proposal:{digest}", request.request_id, plan, request.actor, request.created_at)
