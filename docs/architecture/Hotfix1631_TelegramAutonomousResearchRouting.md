# Hotfix 163.1 - Telegram Autonomous Research Routing

Status: COMPLETE

## Context

Sprints 156 through 163 added deterministic autonomous research contracts for
adaptive validation, planning, critic/retest, Learning Memory integration, and
operational completion checks. Production Telegram conversation still needed a
direct path from natural-language follow-ups into that autonomous research
cycle.

## Problem

After a user asked for a normal research result, follow-up prompts such as
"이 전략을 검증해줘", "문제점을 찾아줘", or "무엇을 배웠어?" could remain in the
presentation/research-summary layer. That meant Telegram did not reliably enter
the autonomous validation/planner/critic/learning path from the prior
authoritative research context.

## Design

Hotfix 163.1 adds a read-only `autonomous_research_cycle` safe tool route for
Telegram conversation.

- Initial research still uses `krx_real_research` or `multi_symbol_research`.
- Explicit autonomous follow-ups resolve against the same-chat structured
  research context.
- The autonomous cycle receives the original request text, canonical symbol,
  baseline metrics, source, fixture flag, and quality status.
- The final Telegram response is rendered from structured tool output by the
  deterministic grounding renderer.
- Learning queries read the stored same-chat autonomous context and do not rerun
  research tools.
- Presentation-only follow-ups do not invoke the autonomous cycle.
- Other Telegram chats cannot read the previous chat's autonomous context.

## Contracts

- No live trading, KIS, broker order, or shell execution.
- No automatic Champion promotion.
- No approval bypass.
- No strategy configuration mutation.
- No fabricated performance metrics.
- Real/fixture provenance and data-quality status remain authoritative.
- Candidate comparisons are advisory unless backed by structured TESTED
  evidence.

## Release Check

```bash
python -m gaon.runtime.cli gaon-telegram-autonomous-research-release-check --db :memory:
```

The release check simulates Telegram messages for:

- initial Samsung research
- autonomous validation
- autonomous critique/improvement
- learning-memory query
- presentation-only short follow-up
- cross-chat isolation

Expected output includes:

```text
gaon-telegram-autonomous-research-release-check: PASS ... grounded=true safety=pass
```

## Rollback

Revert the Hotfix 163.1 commit. Existing research, retest, multi-symbol, and
conversation release checks remain independent of this route.
