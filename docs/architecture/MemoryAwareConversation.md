# Memory-Aware Conversation

Status: Sprint 14 implemented foundation

Memory-aware conversation adds a read-only context layer between Conversation Runtime and Learning Memory.

## Scope

- Build `ConversationContext` for selected research and memory intents.
- Use existing `LearningRepository.retrieve_related` without mutation.
- Fall back deterministically from STRICT to BROAD to GLOBAL retrieval.
- Preserve evidence references, validation state, conflict state, revalidation state, and warnings.
- Treat confidence as a ranking signal only, never as approval.

## Context Objects

- `ConversationContext`
- `RetrievedMemory`
- `ResearchContext`
- `ContextReference`
- `ContextBuildResult`

## Connected Intents

- RECENT_RESEARCH
- SEARCH_MEMORY
- TODAY_PLAN
- RESEARCH_STATUS
- REVALIDATION_DUE
- CONFLICTS
- DUPLICATES

Other intents continue to use the Sprint 13 deterministic persona path without memory lookup.

## Research Context

Sprint 14 includes a read-only `ResearchContextReader` boundary. When no Research Brain storage is connected, Gaon reports that connected records are insufficient instead of inventing research history.

## Safety

The context builder does not:

- save Learning Memory records
- validate knowledge
- resolve conflicts
- change policy
- call external APIs
- access private projects
- execute trading or research jobs
