# Research Brain v3 Architecture

Status: Phase B v3.0 Release Candidate

Research Brain v3 turns a user research question into a deterministic, evidence-backed research artifact. It does not trade, approve itself, call paid APIs by default, or write trusted knowledge without review.

## Pipeline

1. Research request is converted into a validated research plan.
2. Safe evidence providers collect bounded source results.
3. Evidence is normalized, deduplicated, ranked, cited, and budgeted into context.
4. Knowledge proposals are generated from evidence bundles.
5. Approval workflow records explicit approve, reject, or revise decisions.
6. Research orchestration stores run state, checkpoints, and reports.

## Core Modules

- `gaon.research.planning`: bounded request, step, and plan contracts.
- `gaon.research.search`: provider-neutral search contracts and safe providers.
- `gaon.research.evidence`: evidence item, citation, ranking, and context bundle.
- `gaon.research.knowledge`: evidence-backed knowledge proposals.
- `gaon.research.approval_workflow`: explicit human review decisions.
- `gaon.research.orchestration_v3`: durable run state, checkpoint, and report orchestration.

## Run States

`created -> planned -> collecting -> building_context -> synthesizing -> awaiting_review -> completed`

Terminal states are `completed`, `failed`, and `cancelled`. Terminal runs cannot transition again.

Dry-run research may complete deterministically. Non-dry-run research stops at review and does not promote knowledge automatically.

## Persistence

Runtime schema v8 adds:

- `research_brain_runs`
- `research_brain_checkpoints`
- `idx_research_brain_runs_status`

Schema upgrades from v1 through v7 are covered so older runtime databases can migrate into the v8 Research Brain state.

## Safety Boundaries

- No broker, KIS, private repository, account, or live trading dependency.
- No OpenAI, Claude, Gemini, Notion, Telegram, GitHub, or paid API call in automated tests.
- No automatic policy change, trusted knowledge promotion, or user approval.
- Evidence and approval metadata are preserved as review inputs, not as self-approval authority.
