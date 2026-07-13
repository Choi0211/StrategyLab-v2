"""AI research review contracts without external API calls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AIReviewStatus(str, Enum):
    """Review status values."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class AIReviewInput:
    """Deterministic review input."""

    strategy_name: str
    metrics: dict[str, float]
    risk_notes: tuple[str, ...]
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class AIReviewResult:
    """Validated AI research review result."""

    status: AIReviewStatus
    summary: str
    evidence: tuple[str, ...]
    caveats: tuple[str, ...]


def build_review_prompt(review_input: AIReviewInput) -> str:
    """Build deterministic review prompt text."""

    metric_lines = [f"- {key}: {review_input.metrics[key]}" for key in sorted(review_input.metrics)]
    risk_lines = [f"- {note}" for note in review_input.risk_notes]
    assumption_lines = [f"- {item}" for item in review_input.assumptions]
    return "\n".join(
        [
            "StrategyLab AI Research Review",
            f"Strategy: {review_input.strategy_name}",
            "Metrics:",
            *metric_lines,
            "Risk Notes:",
            *risk_lines,
            "Assumptions:",
            *assumption_lines,
            "Return status, summary, evidence, and caveats.",
        ]
    )


def validate_review_result(result: AIReviewResult) -> AIReviewResult:
    """Validate review result schema."""

    if not result.summary:
        raise ValueError("summary is required")
    if not result.evidence:
        raise ValueError("evidence is required")
    return result


def fallback_review(reason: str) -> AIReviewResult:
    """Return explicit fallback when AI review is unavailable."""

    return AIReviewResult(
        status=AIReviewStatus.WARN,
        summary="AI review unavailable; manual review required.",
        evidence=(reason,),
        caveats=("Do not use this review for approval.",),
    )

