"""Runtime event contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from gaon.learning.time import validate_iso8601_utc


class EventType(str, Enum):
    RESEARCH_STARTED = "ResearchStarted"
    RESEARCH_COMPLETED = "ResearchCompleted"
    RESEARCH_FAILED = "ResearchFailed"
    LEARNING_PROPOSAL_CREATED = "LearningProposalCreated"
    DUPLICATE_CANDIDATE_DETECTED = "DuplicateCandidateDetected"
    CONFLICT_CANDIDATE_DETECTED = "ConflictCandidateDetected"
    REVALIDATION_DUE = "RevalidationDue"
    KNOWLEDGE_VALIDATED = "KnowledgeValidated"
    POLICY_APPROVAL_REQUIRED = "PolicyApprovalRequired"
    PREFERENCE_APPROVAL_REQUIRED = "PreferenceApprovalRequired"
    DAILY_REPORT_GENERATED = "DailyReportGenerated"
    WEEKLY_REVIEW_GENERATED = "WeeklyReviewGenerated"
    NOTIFICATION_REQUESTED = "NotificationRequested"
    NOTION_SYNC_REQUESTED = "NotionSyncRequested"
    NOTION_SYNC_COMPLETED = "NotionSyncCompleted"
    NOTION_SYNC_FAILED = "NotionSyncFailed"
    TELEGRAM_MESSAGE_RECEIVED = "TelegramMessageReceived"
    TELEGRAM_RESPONSE_PREPARED = "TelegramResponsePrepared"
    RUNTIME_ERROR_OCCURRED = "RuntimeErrorOccurred"


@dataclass(frozen=True)
class RuntimeEvent:
    event_id: str
    event_type: EventType
    occurred_at: str
    actor: str
    correlation_id: str
    causation_id: str | None
    scope: str
    project: str
    strategy: str
    market: str
    payload: dict[str, Any]
    evidence_refs: tuple[str, ...] = ()
    audit_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        validate_iso8601_utc(self.occurred_at, "occurred_at")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
