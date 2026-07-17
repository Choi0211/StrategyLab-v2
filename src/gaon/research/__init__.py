"""Research Brain contracts for Gaon."""

from gaon.research.brain import (
    ResearchGoal,
    ResearchInterview,
    ResearchJournal,
    ResearchJournalEntry,
    ResearchJournalEntryType,
    ResearchPlan,
    ResearchSession,
    ResearchSessionStatus,
    build_research_plan,
)
from gaon.research.approval import ApprovalDecision, ApprovalRequest, ApprovalStatus, InMemoryApprovalStore
from gaon.research.evidence import Citation, EvidenceBundle, EvidenceItem, build_evidence_bundle, evidence_from_search
from gaon.research.knowledge import KnowledgeClaim as ResearchKnowledgeClaim
from gaon.research.knowledge import KnowledgeProposal, KnowledgeProposalStatus, SQLiteKnowledgeProposalRepository, build_knowledge_proposal, proposal_from_bundle
from gaon.research.orchestrator import InMemoryResearchQueue, QueueItem, ResearchOrchestrator
from gaon.research.planner import plan_research_request
from gaon.research.planning import ResearchPlan as ValidatedResearchPlan
from gaon.research.planning import ResearchStep, ResearchStepType, deterministic_research_plan, provider_backed_research_plan, plan_lifecycle_event, validate_research_plan_steps
from gaon.research.search import FakeSearchProvider, LocalFixtureSearchProvider, OptionalWebSearchProvider, RssAtomSearchProvider, SearchQuery, SearchResult, SourceMetadata
from gaon.research.tasks import ResearchExecutionPlan, ResearchProposal, ResearchRequest, ResearchRun, ResearchRunStatus, ResearchTask, ResearchTaskStatus

__all__ = [
    "ResearchGoal",
    "ResearchInterview",
    "ResearchJournal",
    "ResearchJournalEntry",
    "ResearchJournalEntryType",
    "ResearchPlan",
    "ResearchSession",
    "ResearchSessionStatus",
    "build_research_plan",
    "ApprovalDecision",
    "ApprovalRequest",
    "ApprovalStatus",
    "Citation",
    "EvidenceBundle",
    "EvidenceItem",
    "FakeSearchProvider",
    "InMemoryApprovalStore",
    "InMemoryResearchQueue",
    "KnowledgeProposal",
    "KnowledgeProposalStatus",
    "LocalFixtureSearchProvider",
    "OptionalWebSearchProvider",
    "QueueItem",
    "ResearchExecutionPlan",
    "ResearchOrchestrator",
    "ResearchProposal",
    "ResearchRequest",
    "ResearchRun",
    "ResearchRunStatus",
    "ResearchStep",
    "ResearchStepType",
    "ResearchKnowledgeClaim",
    "ValidatedResearchPlan",
    "build_evidence_bundle",
    "ResearchTask",
    "ResearchTaskStatus",
    "RssAtomSearchProvider",
    "SearchQuery",
    "SearchResult",
    "SourceMetadata",
    "SQLiteKnowledgeProposalRepository",
    "build_knowledge_proposal",
    "plan_research_request",
    "deterministic_research_plan",
    "evidence_from_search",
    "provider_backed_research_plan",
    "plan_lifecycle_event",
    "proposal_from_bundle",
    "validate_research_plan_steps",
]
