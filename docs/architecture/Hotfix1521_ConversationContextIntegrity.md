# Hotfix 152.1 - Conversational Follow-up Context Integrity

Status: COMPLETE

## Context

Sprint 152 introduced deterministic Telegram-facing Korean conversation for
greetings, help, single-symbol research, comparisons, and immediate follow-up
questions. Production-style follow-ups such as "왜 그렇게 판단했어?",
"쉽게 설명해줘", and "자세히 보여줘" must explain the prior research result
from the same chat, not trigger unrelated status/history/champion routes.

## Problem

The previous follow-up path had a weak missing-context fallback. If no in-memory
MVP context existed but an older tool result existed, the brain could fall
through to unrelated tool-result synthesis. Comparison detail rendering also
used only the first payload, which could hide the second symbol.

## Goal

- Preserve typed follow-up context per Telegram chat/session.
- Explain, simplify, and detail the immediately previous research result only.
- Keep real/fixture provenance, source, and data-quality semantics intact.
- Prevent unrelated safe tools from being called for contextual follow-ups.

## Non-goals

- No new LLM provider behavior.
- No trading, KIS, broker, or order routing.
- No Champion promotion, approval bypass, or strategy configuration mutation.
- No database schema migration.

## Context Contract

`ConversationalMVPContext` now stores:

- `last_intent`
- `last_symbols`
- `last_result_kind`
- `last_research_result_ids`
- `last_rendered_result`
- `last_payloads`
- `last_structured_results`
- `last_summary`
- `last_detail_payload`
- `last_source`
- `last_fixture_backed`
- `last_quality_status`
- `created_at`
- `updated_at`

## Invariants

- `fixture_backed=false` responses do not warn about fixture data.
- `source=real` is described as real market data provenance.
- `quality_status=pass` means data-quality pass only, not strategy validity.
- Low trade counts are reported as statistical reliability warnings.
- Missing context returns a deterministic Korean message and calls no tools.
- Greeting/help/status do not erase the last research context.
- Comparison context replaces earlier single-symbol research context.

## Acceptance Criteria

- Single-symbol analysis followed by "왜 그렇게 판단했어?" explains the stored
  single-symbol payload.
- Symbol comparison followed by "쉽게 설명해줘" and "자세히 보여줘" includes all
  compared symbols.
- Follow-ups with no prior research context do not call status, champion, v5, or
  other unrelated tools.
- Chat A context never leaks into Chat B.

## Test Matrix

- Unit renderer tests for missing context and real-source follow-up explanation.
- Telegram integration tests for single, comparison, detail, simplify, greeting
  preservation, context replacement, and chat isolation.
- CLI release check: `gaon-conversation-context-release-check`.

## Operational Verification

```bash
python -m gaon.runtime.cli deployment-import-path-check --expected-source ./src/gaon
python -m gaon.runtime.cli gaon-conversation-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
python -m gaon.runtime.cli gaon-conversation-context-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

Telegram smoke prompts:

- `삼성전자 분석해줘`
- `왜 그렇게 판단했어?`
- `삼성전자와 SK하이닉스 비교해줘`
- `쉽게 설명해줘`
- `자세히 보여줘`

## Rollback

Revert the Hotfix 152.1 commit. No schema migration or persistent data cleanup is
required.

## Completion Checklist

- [x] Unit tests pass
- [x] Integration tests pass
- [x] `scripts/verify_release.py` passes
- [x] Conversation release checks pass
- [x] Documentation updated
- [ ] Working tree clean after commit
