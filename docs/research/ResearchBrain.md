# Research Brain

Status: Sprint 11 Foundation

Research Brain is Gaon's structured research-planning layer.

It does not run trades, call broker APIs, access private MyMoneyGuard files, or approve champions.

## Components

- Research Goal: evidence-backed research question, scope, and success criteria
- Research Plan: deterministic steps for a goal
- Research Session: lifecycle state for a goal and plan
- Research Interview: structured clarification questions and answers
- Research Journal: immutable research notes and decisions

## Evidence Rule

Every Research Brain artifact requires evidence.

The Research Brain reuses `gaon.learning.evidence` rather than creating a second evidence model.

## Learning Memory Rule

Research Goal and Research Plan can be converted into Learning Memory records.

The Research Brain does not replace Learning Memory. It feeds Learning Memory.

## Session Status

Allowed session states:

- `planned`
- `running`
- `completed`
- `blocked`

## Session Transition Table

Allowed transitions:

| From | To |
| --- | --- |
| `planned` | `running`, `blocked` |
| `running` | `completed`, `blocked` |
| `blocked` | `running` |
| `completed` | none |

Completed sessions are terminal and cannot transition again.

## Interview Pending Answers

Research Interview answers may use `null` in JSON, represented as `None` in Python, for unanswered questions.

`pending_questions` returns unanswered questions.

`is_complete` is true only when every question has an answer.

Empty-string answers are rejected. Use `None` for pending answers.

## Versioned JSON

Research Brain objects support versioned JSON round-trip serialization.

Supported objects:

- Research Goal
- Research Plan
- Research Session
- Research Interview
- Research Journal

The current schema version is `1`.

## Sprint 11 Boundary

Included:

- domain contracts
- session transition table
- versioned JSON round-trip support
- deterministic validation rules
- unit tests
- documentation

Excluded:

- strategy generation
- V1 adapter execution
- validation league
- Telegram runtime
- Dashboard runtime
- live trading
