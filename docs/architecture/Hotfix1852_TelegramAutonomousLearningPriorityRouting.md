# Hotfix 185.2 - Telegram Autonomous Learning Priority Routing

Status: COMPLETE

## Problem

Hotfix 185.1 introduced the `autonomous_learning_research` safe tool, but
combined Telegram requests that mixed external research, learned evidence,
candidate generation, validation, and promotion-approval language could still
fall into the legacy autonomous research cycle when an older Samsung research
context already existed.

The production symptom was a legacy response containing fields such as
`adequacy_status`, `planner_steps`, `historical_TESTED_candidates`,
`robust-breakout`, and `regime-filter` instead of an Autonomous Learning V2
stage summary.

## Routing Contract

The Telegram deterministic route now applies this priority:

1. Explicit combined Autonomous Learning V2 intent routes to
   `autonomous_learning_research`.
2. Explicit multi-symbol research routes to `multi_symbol_research`.
3. Explicit fresh KRX real research routes to `krx_real_research`.
4. Simple legacy retest or continuation requests route to
   `research_retest` / `autonomous_research_cycle` unless the active chat
   context is already Autonomous Learning V2.

The combined V2 detector is signal based, not whole-sentence based. It handles
phrases such as "외부 연구", "지금까지 배운 내용", "개선 전략 후보",
"가장 좋은 후보", "승격 승인", "처음부터 다시 연구", and
"전략을 만들어서 검증".

## Context Behavior

- "삼성전자 전략을 더 검증해봐" remains a legacy autonomous research request.
- "계속 연구해줘" after legacy autonomous research continues the legacy cycle.
- "계속 연구해줘" after Autonomous Learning V2 continues V2.
- A combined V2 request overrides a previous legacy or standard Samsung context.

## Safety

The route stays read-only. It does not place orders, call KIS/Broker order
paths, infer approval, mutate strategy configuration, or auto-promote a
Champion. Approval-sounding language still stops at
`requires_human_approval` / `awaiting_human_approval`.

## Release Check

```bash
python -m gaon.runtime.cli gaon-telegram-autonomous-learning-priority-release-check --db :memory:
```

The check proves the production combined request selects
`autonomous_learning_research`, simple validation still selects the legacy
cycle, V2 continuation remains V2, and no `research_retest` or legacy response
leaks into the combined V2 path.
