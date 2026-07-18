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
from gaon.research.approval_workflow import ResearchApprovalDecision, ResearchApprovalRequest, ResearchDecision, SQLiteResearchApprovalRepository, build_approval_request
from gaon.research.evidence import Citation, EvidenceBundle, EvidenceItem, build_evidence_bundle, evidence_from_search
from gaon.research.knowledge import KnowledgeClaim as ResearchKnowledgeClaim
from gaon.research.knowledge import KnowledgeProposal, KnowledgeProposalStatus, SQLiteKnowledgeProposalRepository, build_knowledge_proposal, proposal_from_bundle
from gaon.research.orchestrator import InMemoryResearchQueue, QueueItem, ResearchOrchestrator
from gaon.research.orchestration_v3 import ResearchOrchestratorV3, ResearchReport, ResearchRun as ResearchRunV3, ResearchRunState, SQLiteResearchRunRepository
from gaon.research.planner import plan_research_request
from gaon.research.planning import ResearchPlan as ValidatedResearchPlan
from gaon.research.planning import ResearchStep, ResearchStepType, deterministic_research_plan, provider_backed_research_plan, plan_lifecycle_event, validate_research_plan_steps
from gaon.research.search import FakeSearchProvider, LocalFixtureSearchProvider, OptionalWebSearchProvider, RssAtomSearchProvider, SearchQuery, SearchResult, SourceMetadata
from gaon.research.tasks import ResearchExecutionPlan, ResearchProposal, ResearchRequest, ResearchRun, ResearchRunStatus, ResearchTask, ResearchTaskStatus

__all__ = [
    "ResearchGoal",
    "ResearchApprovalDecision",
    "ResearchApprovalRequest",
    "ResearchDecision",
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
    "ResearchOrchestratorV3",
    "ResearchProposal",
    "ResearchRequest",
    "ResearchRun",
    "ResearchRunStatus",
    "ResearchRunState",
    "ResearchRunV3",
    "ResearchReport",
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
    "SQLiteResearchApprovalRepository",
    "SQLiteResearchRunRepository",
    "build_approval_request",
    "build_knowledge_proposal",
    "plan_research_request",
    "deterministic_research_plan",
    "evidence_from_search",
    "provider_backed_research_plan",
    "plan_lifecycle_event",
    "proposal_from_bundle",
    "validate_research_plan_steps",
]
