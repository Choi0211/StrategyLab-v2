# Sprint 169 — Knowledge Conflict Resolution Foundation

Status: IMPLEMENTED

## Goal

Prevent Gaon from silently treating conflicting research claims as settled
knowledge.

## Input

Sprint 169 operates on Sprint 168 Knowledge Candidates.

Each comparable candidate receives explicit structured metadata:

- topic_key
- stance: SUPPORTS / OPPOSES / NEUTRAL

Sprint 169 does not infer stance from arbitrary free text.

That semantic layer may be added later behind separate validation.

## Conflict States

### SUPPORTED

At least two independent sources provide directional evidence in the same
direction.

SUPPORTED still does not mean Validated Knowledge.

### UNRESOLVED_CONFLICT

Independent sources provide opposing directional claims.

Gaon must preserve the disagreement.

Evidence-score advantage does not automatically resolve the conflict.

### INSUFFICIENT_INDEPENDENCE

Evidence exists, but there are not enough independent sources.

Multiple claims from one source do not count as independent corroboration.

### NO_COMPARABLE_EVIDENCE

No directional claim is available for the topic.

## Source Independence

Independent-source count is based on source_id.

Several claims from one paper/article/document still count as one source.

For evidence scoring, only the strongest same-direction claim per source is
counted to avoid duplicate inflation.

## Non-Negotiable Boundary

A conflict result always starts with:

- knowledge_validated = false
- production_approved = false
- policy_applied = false
- automatic_resolution = false

## Safety

Sprint 169 cannot:

- fabricate semantic contradiction
- auto-select the more convenient claim
- auto-validate knowledge
- mutate research policy
- mutate production strategy
- auto-promote Champion
- activate KIS/Broker trading
- place live orders

## Future

Later Sprints can add:

- corroboration graphs
- semantic claim normalization
- temporal conflict handling
- research-gap generation
- targeted autonomous source search

Those layers must preserve this conflict record instead of overwriting it.
