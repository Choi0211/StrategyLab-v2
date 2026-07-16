# RFC-0002: Sprint 11 Research Brain

Status: Accepted for Sprint 11  

## Problem

Gaon needs a Research Brain foundation that turns a research request into structured, evidence-backed planning artifacts before later sprints add strategy generation, V1 adapter contracts, validation, dashboard, or Telegram flows.

## Proposal

Add `gaon.research` with:

- `ResearchGoal`
- `ResearchPlan`
- `ResearchSession`
- `ResearchInterview`
- `ResearchJournal`
- `ResearchJournalEntry`

The package reuses `gaon.learning.evidence` and `gaon.learning.memory` instead of modifying the existing Learning Memory core.

## Acceptance Criteria

- Research goals require evidence and export a Learning Memory record.
- Research plans require steps and export a Learning Memory record.
- Sessions reject mismatched goal/plan pairs.
- Sessions reject invalid transitions.
- Completed sessions cannot transition again.
- Interviews require aligned questions and answers.
- Interviews can represent unanswered questions.
- Journals are immutable and reject duplicate entries.
- Research Brain objects support versioned JSON round-trip serialization.
- Unit tests, integration tests, and release verification pass.

## Non-Goals

- No broker or KIS API.
- No private MyMoneyGuard access.
- No source-code self-modification.
- No prompt mutation.
- No Dashboard or Telegram runtime.
