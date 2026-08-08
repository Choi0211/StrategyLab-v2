# Hotfix 155.1 - Conversational Re-execution Integrity

Status: COMPLETE

## Context

Sprint 155 connected Telegram period-change follow-ups to authoritative
research re-execution. Production testing found that multi-symbol follow-up
reruns could render `unknown(unknown)` because the conversation layer expected a
legacy `symbols` summary, while the real `multi_symbol_research` safe tool
returns `evidence` records.

## Problem

The mismatch could corrupt presentation context after requests such as
`3년으로 다시 비교해줘`. Follow-up typo variants such as `비겨해줘` also needed
narrow tolerance, and data-quality warnings needed concise default presentation
without losing detailed stored evidence.

## Fix

- Normalize production `multi_symbol_research` `evidence` payloads into the
  same authoritative research payload contract used by renderers.
- Fail closed when a successful safe-tool result lacks symbol identity or
  structured metrics.
- Preserve explicit period parsing for `최근 3년`, `3년`, `5년`, and
  `2021년부터` forms.
- Add narrow typo tolerance for `비겨` and `sk하이닏스`.
- Summarize data-quality warnings by default and expose detailed stored
  quality evidence only on explicit follow-up such as `데이터 문제 자세히 보여줘`.

## Invariants

- No live trading, broker/KIS order, Champion auto-promotion, approval bypass,
  or strategy configuration mutation.
- Presentation follow-ups do not rerun research.
- All rendered performance metrics must come from structured safe-tool output.
- Unknown or malformed multi-symbol results are blocked rather than rendered.

## Verification

Release check:

```bash
python -m gaon.runtime.cli gaon-conversational-reexecution-integrity-release-check --db :memory:
```

The check verifies period parsing, multi-symbol context reuse, typo
normalization, warning summarization, explicit warning detail rendering, and the
unknown-result guard.
