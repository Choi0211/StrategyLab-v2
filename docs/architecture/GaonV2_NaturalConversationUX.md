# Gaon V2 Natural Conversation UX

Status: COMPLETE

## Context

Gaon V2 already has authoritative production research, validation, promotion,
approval, Champion, and rollback paths. The final UX closeout improves only the
Telegram/user-facing rendering of those existing structured results.

## Problem

`autonomous_learning_research` produced correct authoritative payloads, but the
default Telegram answer exposed developer-oriented fields such as
`partner_status=`, `validation_coverage=`, `source_ids=`, fingerprints, blocker
codes, and execution-state labels. Follow-up questions about OOS, transaction
costs, Monte Carlo, or approval could fall back to generic responses unless they
matched existing presentation phrases.

## Design

- Default autonomous-learning answers are rendered as natural Korean research
  explanations.
- Raw/detail developer fields are shown only for explicit detail requests such
  as `raw 결과 보여줘`, `상세 검증 결과 보여줘`, or fingerprint/source-id style
  diagnostic prompts.
- Follow-up explanation questions reuse the stored authoritative conversation
  context and do not rerun research tools.
- The formatter reads only existing structured payload fields. It does not
  calculate new metrics, fabricate validation status, mutate strategy state, or
  request approval unless the authoritative promotion status already allows it.
- The implementation extends existing `research_grounding` and
  `LLMConversationBrain` context handling. It does not add a second research,
  validation, promotion, memory, or conversation engine.

## Default Response

The default answer focuses on:

- what was researched
- authoritative data source and trade/sample summary
- which validation sections ran or remain insufficient
- external research/provenance at a user-readable level
- candidate count and tournament status
- promotion readiness or blockers
- safety boundary confirmation

Internal audit fields remain available through explicit detail requests.

## Follow-Up Context

Questions such as `OOS가 뭐야?`, `거래비용에는 왜 약해?`, and
`Monte Carlo는 했어?` are treated as explanation follow-ups when a prior
authoritative research context exists. The response is grounded in the stored
payload and includes no new tool execution.

## Approval Conversation

If the authoritative payload reports `requires_human_approval`, the response may
ask whether to proceed with Stage 1 approval while clearly stating that no
strategy change has occurred yet. If the payload is blocked or needs more
evidence, Gaon explains the remaining blockers and does not ask for approval.

## Safety

Schema remains v36. The UX layer preserves:

- no live trading
- no KIS/Broker orders
- no Champion auto-promotion
- no approval bypass
- no strategy config mutation
- no fabricated metrics or fixture leakage
