# Hotfix 154.1 - Presentation State and Grounding Integrity

Status: COMPLETE

## Context

Sprint 154 introduced a natural presentation layer on top of Sprint 153
evidence-bound reasoning. Production Telegram testing showed that repeated
presentation-only follow-ups could let prior style/length preference influence
later explicit requests.

Observed flow:

1. `삼성전자 분석해줘`
2. `지금 사도 돼?`
3. `한 줄로 말해줘`
4. `비유해서 설명해줘`
5. `예를 들어 설명해줘`
6. `전문적으로 설명해줘`
7. `전문용어 빼줘`
8. `조금 더 짧게`
9. `자세히 보여줘`

## Problem

- A short/plain-language follow-up could keep stale short preference and block a
  later detailed presentation request.
- Short presentation output could omit authoritative source metadata even though
  it existed in the structured research context.
- The presentation model did not explicitly track output format, making table
  and detailed/bulleted render intent less clear.
- MDD numeric examples needed clearer wording that the calculation is an
  illustrative application of MDD to initial capital, not a claim about realized
  cash loss timing.

## Goal

Separate authoritative research context from presentation state more explicitly.
Presentation requests may change style, depth, length, and format, but they may
not change facts such as symbol, source, fixture flag, quality status, period,
metrics, or capital assumptions.

## Non-goals

- No schema migration.
- No provider/LLM rewrite.
- No new research, backtest, or market data logic.
- No Telegram write/config mutation.
- No trading, broker/KIS order, or Champion promotion.

## Design

- Add a `PresentationFormat` contract with `prose`, `bullets`, and `table`.
- Preserve explicit current-message precedence over previous preference.
- Treat `자세히 보여줘`, `상세히`, `원본`, and `전체 결과` as detailed/long
  bulleted report requests even if the previous state was one-line or short.
- Treat `표로` as table format.
- Keep `조금 더 짧게` deterministic by re-rendering from structured evidence,
  not by summarizing the previous response string.
- Include authoritative source in presentation subject context so short/plain
  renderers do not degrade known source into unknown-source language.
- Use exactly one final renderer path per request.

## Authoritative Fields

Presentation must read these only from structured context:

- symbol and company name
- source and fixture flag
- quality status
- period
- trade count
- total return
- MDD
- win rate
- profit factor
- CAGR
- Sharpe
- expectancy
- exposure
- initial capital
- ending equity

## Acceptance Criteria

- `전문용어 빼줘` followed by `조금 더 짧게` returns one deterministic short
  presentation, with source preserved and no duplicate report sections.
- `한 줄로 말해줘` followed by `자세히 보여줘` returns detailed metrics and is
  not blocked by previous short preference.
- `비유해서`, `전문적으로`, and `전문용어 빼줘` keep the same authoritative
  research facts while changing only presentation.
- MDD examples use authoritative `initial_capital` and `mdd` and explicitly say
  the calculation is illustrative.
- Presentation-only follow-ups do not rerun the research/provider tool.
- No internal metadata, unsupported recommendation, or unknown-source wording is
  exposed.

## Release Check

```powershell
python -m gaon.runtime.cli gaon-presentation-integrity-release-check --db :memory:
```

## Test Matrix

- Unit: preference precedence, grounded source preservation, MDD example wording.
- Integration: production-equivalent Telegram sequence, no duplicate renderer,
  no research rerun, source/quality preservation, detail-after-short behavior.
- Release: `gaon-presentation-integrity-release-check`.

## Rollback

Revert the Hotfix 154.1 commit. Schema remains v36, and all changes are limited
to presentation rendering, CLI release checks, tests, and docs.

## Completion Checklist

- [x] Root cause identified.
- [x] Preference precedence model updated.
- [x] Source grounding preservation added.
- [x] Single-renderer behavior tested.
- [x] Release check added.
- [x] Unit and integration tests added.
- [x] Full verification complete.
- [x] Commit created.
