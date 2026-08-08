# Sprint 170 — Knowledge Gap & Research Question Generation

Status: IMPLEMENTED

## Goal

Convert unresolved knowledge states into bounded and explicit future
research questions.

Sprint 170 answers:

"What does Gaon still need to know?"

It does not answer the research question itself.

## Input

Sprint 169 `KnowledgeConflictRecord`.

## Gap Mapping

### UNRESOLVED_CONFLICT

Produces:

`CONTRADICTION`

Priority:

`HIGH`

The research objective is to obtain independent evidence capable of
explaining or resolving the disagreement.

### INSUFFICIENT_INDEPENDENCE

Produces:

`INSUFFICIENT_INDEPENDENCE`

The research objective is to find independent corroborating or challenging
evidence.

### NO_COMPARABLE_EVIDENCE

Produces:

`MISSING_DIRECTIONAL_EVIDENCE`

The research objective is to acquire comparable directional evidence.

### SUPPORTED

Produces no new gap.

This prevents endless research when the current evidence state does not
require another knowledge-gap task.

## Research Question Contract

Each question records:

- question_id
- topic_key
- parent_conflict_id
- source conflict state
- gap type
- priority
- required evidence
- minimum independent source count
- stop conditions

## Research Queue

Sprint 170 introduces a bounded queue contract.

Each entry has:

- sequence
- attempts
- max_attempts
- status
- auto_execute=false

Duplicate question IDs are collapsed.

High priority questions are ordered first.

## Safety

A generated question is not:

- a fact
- validated knowledge
- a strategy recommendation
- approval
- an executable instruction

Every question remains:

- knowledge_validated=false
- production_approved=false
- policy_applied=false
- execution_authorized=false

Every queue entry remains:

- auto_execute=false

Sprint 170 cannot:

- search the Internet
- download a source
- execute external content
- change a strategy
- promote Champion
- enable KIS/Broker trading
- place an order

## Next

Sprint 171 may connect this bounded queue to a safe Source Discovery layer.

That future layer must preserve:

Research Question
→ Source Discovery
→ Provenance
→ Evidence Gate
→ Claim
→ Conflict Re-evaluation

and must never allow downloaded material to bypass existing evidence gates.
