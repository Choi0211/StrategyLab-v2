# Sprint 155 - Conversational Research Execution

Status: IN PROGRESS

## Context

Sprints 152 through 154 made Telegram conversation natural and presentation-aware,
but period-change follow-ups such as `5년으로 다시 해봐` still stopped at a
boundary prompt or stayed in presentation mode. Sprint 155 connects explicit
conversation follow-ups to the existing authoritative KRX research safe tools.

## Problem

Users naturally ask for the same research to be rerun with a different period.
Gaon must reuse the same chat-scoped research context, symbol set, strategy text,
and assumptions without parsing the previous rendered answer or inventing new
facts.

## Goal

- Resolve explicit period rerun requests from the same Telegram conversation.
- Execute `krx_real_research` or `multi_symbol_research` through the existing
  safe tool path.
- Render Korean summaries from structured authoritative results only.
- Ask for clarification when the period or prior context is missing.

## Non-goals

- No new backtest engine.
- No live trading, KIS/Broker order, or automatic Champion promotion.
- No approval bypass and no strategy configuration mutation.
- No LLM-generated Python, shell, SQL, or arbitrary provider output as fact.

## Scope

- `ConversationalResearchExecutionRequest`
- `ConversationalResearchExecutionResult`
- Deterministic period resolution for `3년`, `5년`, recent year requests, and
  `YYYY년부터 지금까지`
- Single-symbol and multi-symbol rerun routing
- Telegram conversation integration
- Release check: `gaon-conversational-research-execution-release-check`

## Contracts and Invariants

- Explicit user fields override inferred context.
- Missing symbol context or ambiguous period is fail-closed with clarification.
- Previous strategy/assumptions are reused only from structured stored payloads.
- Presentation preferences cannot mutate research facts or trigger reruns.
- Returned metrics must come from authoritative safe tool output.
- Internal IDs such as run IDs, strategy fingerprints, and validation IDs remain
  hidden in default Telegram responses.

## Acceptance Criteria

- `삼성전자 분석해줘` then `더 긴 기간으로 다시 분석해봐` asks for a period.
- `삼성전자 분석해줘` then `5년으로 다시 해봐` reruns Samsung with the previous
  strategy context.
- `더 길게 다시 해봐` then `3년` keeps context and executes.
- `삼성전자와 SK하이닉스 비교해줘` then `3년으로 다시 비교해줘` executes
  multi-symbol research for both symbols.
- `5년으로 다시 해봐` without previous context does not invent a symbol.
- `조금 더 짧게` remains a presentation-only follow-up.

## Test Matrix

- Unit: contract period resolution, explicit symbol override, multi-symbol
  comparison detection, structured-text reuse, renderer metadata hiding.
- Integration: Telegram conversation rerun, clarification, multi-symbol rerun,
  presentation isolation, missing-context fail-closed behavior.
- CLI: `gaon-conversational-research-execution-release-check`.

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-conversational-research-execution-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

For production Telegram verification, use:

- `삼성전자 분석해줘`
- `더 긴 기간으로 다시 분석해봐`
- `5년으로 다시 해봐`
- `삼성전자와 SK하이닉스 비교해줘`
- `3년으로 다시 비교해줘`

## Rollback

Revert the Sprint 155 commit. The prior boundary behavior returns because the
existing `render_rerun_boundary` path remains available.

## Documentation

Updated README, Telegram operations, changelog, release notes, and test results.

## Completion Checklist

- [x] Typed contracts added
- [x] Safe tool period arguments wired
- [x] Telegram context rerun path added
- [x] Tests added
- [x] Release check added
- [ ] Full verification completed
