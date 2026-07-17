"""Read-only conversation context contracts."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.runtime.intents import Intent


@dataclass(frozen=True)
class ContextReference:
    reference_id: str
    source: str
    summary: str


@dataclass(frozen=True)
class RetrievedMemory:
    record_id: str
    content: str
    record_type: str
    validation_state: str
    confidence: float
    conflict_state: str
    revalidation_state: str
    warnings: tuple[str, ...]
    references: tuple[ContextReference, ...]


@dataclass(frozen=True)
class ResearchContext:
    sessions_summary: str
    outcomes_summary: str
    warnings: tuple[str, ...]
    references: tuple[ContextReference, ...] = ()


@dataclass(frozen=True)
class ConversationContext:
    conversation_id: str
    user_id: str
    query: str
    intent: Intent
    project: str
    strategy: str
    market: str
    retrieved_records: tuple[RetrievedMemory, ...]
    claims: tuple[str, ...]
    research: ResearchContext
    warnings: tuple[str, ...]
    references: tuple[ContextReference, ...]
    generated_at: str


@dataclass(frozen=True)
class ContextBuildResult:
    context: ConversationContext
    route_suffix: str = "context"
