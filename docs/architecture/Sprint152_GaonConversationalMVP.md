# Sprint 152: Gaon Conversational MVP

Status: IMPLEMENTED

## Context

Sprint 151 added dynamic KRX universe selection for multi-symbol research. Sprint 152 returns to the Telegram user experience: Gaon must understand common Korean research requests and render verified research results in a human-readable form without exposing internal JSON or fabricated metrics.

## Problem

The existing Telegram path can execute safe research tools, but user-facing responses may still feel like structured system output. Clear requests such as greetings, single-symbol analysis, symbol comparisons, and follow-up questions need deterministic routing and Korean summaries that preserve strict grounding.

## Goal

Add a deterministic conversational MVP for Telegram that supports:

- greeting
- help
- single_symbol_analysis
- compare_symbols
- multi_symbol_analysis classification
- explain_previous_result
- simplify_previous_result
- show_details
- status_query
- unknown fallback

## Non-goals

- General ChatGPT clone
- Long-term memory
- Voice response
- Plugin or scheduler expansion
- Auto orders or KIS/broker integration
- Automatic Champion promotion
- User-unapproved strategy configuration changes
- Relaxing KRX data quality gates

## Scope

- Deterministic Korean intent classification for clear user messages
- Korean KRX symbol extraction for supported public symbols
- Human-readable deterministic single-symbol and comparison renderers
- Per-session recent result context for immediate follow-up questions
- `gaon-conversation-release-check`
- Unit and integration tests for Telegram conversational behavior

## Contracts And Invariants

- Real and fixture-backed data remain explicitly separated.
- All metrics shown to the user must come from structured safe-tool output.
- `krx_real_research` remains read-only.
- Partial comparison failure is fail-closed; Gaon does not rank using successful symbols only.
- Greeting does not dump status, run IDs, logs, or recent research state.
- Internal fields such as validation IDs, raw fixture booleans, Python `None`, and raw class names are hidden by default.
- Detailed output is only shown for explicit detail requests.
- Telegram context is scoped by session/chat ID.

## Acceptance Criteria

- "안녕하세요" returns a natural Korean greeting with "영하님" and "가온".
- "삼성전자 분석해줘" routes to `krx_real_research` and returns a concise Korean summary.
- "삼성전자와 SK하이닉스 비교해줘" executes both symbols under the same assumptions and renders a comparison.
- "왜 그렇게 판단했어?", "쉽게 설명해줘", and "자세히 보여줘" use the previous result in the same Telegram chat only.
- Low sample size, fixture-backed data, infinite Profit Factor, and data quality warnings are surfaced as Korean reliability warnings.
- No trading, approval, Champion promotion, or config mutation is introduced.

## Test Matrix

- Unit: intent classification, symbol extraction, renderer internal-field suppression
- Integration: Telegram greeting, single-symbol analysis, symbol comparison, follow-up context, context isolation, partial failure
- Release check: `gaon-conversation-release-check`
- Regression: full unit tests, full integration tests, `scripts/verify_release.py`, deployment import path check, `git diff --check`

## Operational Verification

After deployment:

```powershell
python -m gaon.runtime.cli deployment-import-path-check --expected-source ./src/gaon
python -m gaon.runtime.cli gaon-conversation-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

Telegram smoke prompts:

- 안녕하세요
- 삼성전자 분석해줘
- 삼성전자와 SK하이닉스 비교해줘
- 왜 그렇게 판단했어?
- 쉽게 설명해줘
- 자세히 보여줘

## Rollback

Revert the Sprint 152 feature commit. The change does not require a database migration and does not mutate strategy configuration.

## Documentation

- README
- ReleaseNotes
- CHANGELOG
- TestResults
- This Sprint brief

## Completion Checklist

- [x] Implementation complete
- [x] Unit tests pass
- [x] Integration tests pass
- [x] `scripts/verify_release.py` pass
- [x] Release check pass
- [x] Documentation updated
- [x] Working tree clean after commit
