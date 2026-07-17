# Research Assistant Orchestration

Status: Sprint 16 guarded orchestration foundation

Research Assistant Orchestration turns natural-language research requests into deterministic proposals, approval requests, runs, and queue items.

## Scope

- Deterministic research proposal creation.
- Explicit approval object and token validation.
- Research run state machine.
- In-memory deterministic queue.
- Audit event strings for state changes.
- LearningProposal remains a proposal only; no automatic Learning Memory save.

## Run States

- proposed
- awaiting_approval
- approved
- running
- paused
- completed
- failed
- cancelled

`completed`, `failed`, and `cancelled` are terminal. Running requires explicit approval token.

## Safety

The orchestrator does not:

- place orders
- call broker APIs
- run shell commands
- execute arbitrary Python
- perform unbounded search
- auto-approve
- auto-validate knowledge
- mutate Learning Memory
