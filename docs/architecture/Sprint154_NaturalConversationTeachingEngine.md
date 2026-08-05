# Sprint 154 Natural Conversation & Teaching Engine

Status: IN PROGRESS

## Context

Sprint 153 separated evidence-bound reasoning from free-form provider text. Gaon can now answer investment, risk, strategy, rerun, and follow-up questions from structured research context. Sprint 154 adds a presentation layer on top of that reasoning result so the same evidence can be explained naturally, briefly, professionally, or in a teaching style without changing the underlying research facts.

## Problem

The Sprint 153 response shape is safe but often reads like a compact report. Telegram users may ask for the same result in a shorter, easier, more professional, analogy-based, example-based, or table-based form. Those requests must not trigger a new research run, fabricate metrics, expose internal metadata, or weaken the recommendation guard.

## Goal

Add deterministic natural conversation and teaching presentation for existing authoritative research context:

- Direct answer first.
- Adjustable conversation style, explanation depth, and response length.
- Teaching analogies and numeric examples only from structured evidence.
- Session-scoped presentation preference within the same Telegram chat.
- No new research execution for presentation-only follow-ups.

## Non-goals

- Long-term user memory.
- General ChatGPT clone behavior.
- Voice UI.
- News gathering or web search.
- Investment recommendation or order execution.
- Strategy mutation, portfolio allocation, or automatic Champion promotion.
- Hidden chain-of-thought exposure.

## User Scenarios

- "삼성전자 지금 사도 돼?"
- "한 줄로 말해줘"
- "쉽게 설명해줘"
- "비유해서 설명해줘"
- "예를 들어 설명해줘"
- "전문적으로 설명해줘"
- "전문용어 빼줘"
- "보고서로 정리해줘"
- "표로 보여줘"

## Conversation Style Model

`ConversationStyle`:

- `concise`
- `conversational`
- `explanatory`
- `teaching`
- `professional`
- `report`

The default is `conversational`. Style is separate from reasoning depth so Gaon can explain the same `ConversationReasoningResult` in different forms without changing evidence.

## Explanation Style Model

Sprint 154 keeps Sprint 153's reasoning levels and adds presentation-facing `ExplanationDepth`:

- `simple`
- `standard`
- `professional`
- `detailed`

`professional` includes terms such as MDD, Sharpe, Profit Factor, Exposure, and trade_count. `simple` avoids unnecessary technical terms.

## Length Control

`ResponseLength`:

- `one_line`: one compact paragraph.
- `short`: short answer.
- `medium`: default natural answer.
- `long`: report/detail style.

Explicit style changes reset stale length preference unless the same message also asks for a specific length.

## Difficulty Control

Simple and teaching requests use plain Korean and avoid unnecessary mixed Korean/English terms. Professional requests preserve exact metric names and units.

## Analogy Contract

Analogies are explanatory only. They must not create facts, future price claims, or buy/sell pressure.

Approved deterministic analogies:

- Low trade count: like judging skill from one or two exam questions.
- MDD: like checking how far assets fell from a high point.
- Profit Factor `inf`: no loss sample means the ratio is hard to interpret.
- Exposure: time actually spent in the market.
- Data quality pass: input data passed checks, not strategy validity.

## Example Contract

Numeric examples are allowed only when required inputs exist in structured payloads. For MDD examples:

- `drawdown_amount = initial_capital * mdd`
- `remaining_equity = initial_capital * (1 - mdd)`

If `initial_capital` is missing, Gaon does not invent an example amount.

## Evidence Preservation

Presentation may use only:

- dataset metadata
- source and fixture provenance
- data quality
- BacktestResult metrics
- ValidationReport
- tested candidate comparison
- current conversation context

The renderer suppresses internal metadata such as `strategy_fingerprint`, `fixture_backed`, `quality_status=`, `validation_id`, and raw schema fields.

## Safety Constraints

- No live trading.
- No KIS or broker order.
- No Champion auto-promotion.
- No approval bypass.
- No strategy mutation.
- Fail-closed evidence boundaries.
- Real/fixture distinction preserved.
- Canonical symbols preserved.
- Telegram chat isolation preserved.
- Session context persistence preserved.
- Metric unit integrity preserved.
- Recommendation guard preserved.

## Acceptance Criteria

- Natural answers start with the direct answer to the user's question.
- Conversational style does not expose bracketed report headings.
- One-line requests return a one-line response.
- Teaching requests include a grounded analogy.
- Example requests include exact numeric calculations only when inputs exist.
- Professional requests include technical metrics and units.
- Presentation-only follow-ups do not call research tools again.
- Session style preference is scoped to a single chat.
- Greeting/help do not clear research context or preference.
- Internal metadata remains hidden.

## Test Matrix

- Unit tests for style, depth, length, direct answer, teaching analogy, numeric example, metadata suppression, and recommendation guard.
- Telegram integration tests for same-chat context reuse, presentation preference, and no extra tool calls.
- CLI release check `gaon-natural-conversation-release-check`.
- Existing Sprint 152 and Sprint 153 release checks remain required.

## Operational Verification

```powershell
python -m gaon.runtime.cli gaon-natural-conversation-release-check --db :memory:
python -m gaon.runtime.cli gaon-conversational-reasoning-release-check --db :memory:
python -m gaon.runtime.cli deployment-import-path-check --expected-source .\src\gaon
```

Production Telegram verification should use an existing research context, then send:

- `한 줄로 말해줘`
- `비유해서 설명해줘`
- `예를 들어 설명해줘`
- `전문적으로 설명해줘`
- `전문용어 빼줘`

## Rollback

Revert the Sprint 154 commit. The schema is unchanged, and presentation preference is stored only in existing session metadata under `conversation_mvp`.

## Completion Checklist

- [x] Blueprint reviewed.
- [x] Sprint brief written.
- [x] Typed presentation model implemented.
- [x] Natural renderer implemented.
- [x] Teaching analogy and example contracts implemented.
- [x] Session preference implemented.
- [x] CLI release check added.
- [x] Unit and integration tests added.
- [x] Full verification complete.
- [x] Commit created.
