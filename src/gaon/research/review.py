"""Research review contracts."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.learning.contracts import LearningProposal


@dataclass(frozen=True)
class ResearchReview:
    review_id: str
    run_id: str
    evidence: tuple[str, ...]
    limitations: tuple[str, ...]
    contradictory_findings: tuple[str, ...]
    confidence: float
    revalidation_recommendation: str


def learning_proposal_from_review(review: ResearchReview, proposal: LearningProposal) -> LearningProposal:
    return proposal
