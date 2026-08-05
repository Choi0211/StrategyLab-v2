# Sprint 153 Conversational Reasoning & Explanation Engine

Status: COMPLETE

## Context

Sprint 152 gave Gaon a deterministic Telegram conversational MVP. Hotfixes
152.1 through 152.3 made follow-up context persistent, corrected typo handling,
and protected metric units and presentation integrity.

Sprint 153 extends that foundation from "show the result again" to
evidence-bound explanation. Gaon must answer why, risk, professional
explanation, recommendation, and investment-decision-style questions without
exposing chain-of-thought or inventing unsupported claims.

## Problem

Telegram users ask questions such as:

- `삼성전자 지금 사도 돼?`
- `위험은 어느 정도야?`
- `전문적으로 설명해줘`
- `그럼 지금 사도 돼?`
- `3년 기간으로 다시 해줘`

Before this sprint, these prompts could fall back to generic responses or reuse
the previous report shape too literally. They needed a structured explanation
contract that separates conclusion, evidence, limitations, risk, and next
validation.

## Goal

Add a deterministic conversational reasoning layer that:

- classifies explanation and decision-oriented intents;
- chooses an explanation level;
- builds a typed reasoning result from structured evidence only;
- renders natural Korean explanations;
- refuses unsupported investment recommendations and automatic actions;
- preserves existing authoritative research, context persistence, metric units,
  and metadata suppression.

## Non-goals

- No chain-of-thought disclosure.
- No generic ChatGPT clone behavior.
- No long-term personal memory expansion.
- No new web search, news, or external provider integration.
- No portfolio allocation.
- No live trading, KIS/broker order, or Telegram configuration mutation.
- No Champion auto-promotion.
- No automatic strategy mutation.

## User Scenarios

- A user asks whether a researched symbol can be bought now. Gaon explains that
  the current evidence is insufficient for a buy recommendation and lists what
  must be verified next.
- A user asks about risk after a single-symbol or comparison result. Gaon
  explains trade count, MDD, exposure, and sample-size limitations.
- A user asks for a professional explanation. Gaon expands the explanation with
  MDD, Sharpe, Profit Factor, exposure, and statistical reliability notes.
- A user asks for a rerun or timeframe change. Gaon does not silently mutate
  assumptions; it asks for explicit authoritative rerun parameters.
- A user asks a follow-up in another Telegram chat. Gaon does not reuse context
  across chats.

## Intent Model

Sprint 153 extends `ConversationalMVPIntent` with:

- `professional_explanation`
- `investment_decision_question`
- `risk_question`
- `strategy_question`
- `timeframe_change_request`
- `rerun_request`
- `recommendation_request`
- `contextual_followup`

Deterministic rules take priority for explicit Korean/English phrases. Safety
intents are intentionally narrow and do not use broad fuzzy matching.

## Explanation-Level Model

`ExplanationLevel` supports:

- `simple`
- `standard`
- `professional`
- `detailed`

Default level is `standard`. Simple output compresses to conclusion, reason,
limitation, and next step. Professional output includes metric interpretation
for MDD, Sharpe, Profit Factor, and exposure.

## Evidence Contract

The reasoning layer uses immutable dataclasses:

- `ConversationReasoningRequest`
- `ConversationReasoningResult`
- `EvidencePoint`
- `Limitation`
- `RiskPoint`
- `NextAction`
- `DecisionBoundary`

Evidence is derived from structured `krx_real_research` payloads or persisted
conversation context. Free text is not treated as evidence.

## Reasoning Summary Contract

User-facing reasoning output is organized as:

1. Conclusion
2. Core evidence
3. Limitations
4. Risks
5. What cannot be concluded
6. Next validation or possible action

This is a summary of structured evidence, not hidden chain-of-thought.

## Context Resolution

Telegram follow-ups resolve context from the same session only. Greeting, help,
status, typo, and unknown responses do not erase the prior research context.
Missing-context risk or explanation requests return a deterministic
missing-context message without calling unrelated tools.

## Rendering Modes

- `simple`: 3-6 sentence style with minimal terminology.
- `standard`: sectioned conclusion/evidence/limitations/risk/next-step output.
- `professional`: adds MDD, Sharpe, Profit Factor, exposure, and reliability
  interpretation.
- `detailed`: preserves the Hotfix 152.3 detail renderer while keeping internal
  IDs hidden.

## Safety Constraints

- No live trading.
- No KIS/broker order.
- No Champion auto-promotion.
- No approval bypass.
- No strategy mutation.
- Fail closed on unsupported or missing evidence.
- Preserve real/fixture distinction.
- Preserve canonical KRX symbols and explicit symbol precedence.
- Preserve Telegram chat isolation and session context persistence.
- Preserve metric unit integrity and internal metadata suppression.

## Acceptance Criteria

- `삼성전자 지금 사도 돼?` routes to investment-decision reasoning and does not
  recommend buying.
- `위험은 어느 정도야?` uses the previous research context and explains MDD,
  trade count, and sample limitations.
- `전문적으로 설명해줘` includes MDD, Sharpe, Profit Factor, exposure, and
  statistical limitation wording.
- `3년 기간으로 다시 해줘` is treated as a rerun/timeframe request, not as a
  simple explanation.
- Missing-context follow-ups do not call research, Champion, status, V5, or
  history tools.
- Default responses hide internal IDs, raw provenance keys, and raw schema
  names.

## Test Matrix

- Intent classification for decision, risk, strategy, professional explanation,
  timeframe change, rerun, recommendation, and contextual follow-up.
- Explanation-level selection for simple, standard, professional, and detailed.
- Typed reasoning result creation from structured payloads.
- Investment-decision guard for insufficient evidence.
- Zero-trade risk wording that does not imply safety.
- Telegram same-chat multi-message reasoning flow.
- Telegram missing-context risk follow-up.
- Release check `gaon-conversational-reasoning-release-check`.

## Operational Verification

```bash
python -m gaon.runtime.cli deployment-import-path-check --expected-source ./src/gaon
python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:
python -m gaon.runtime.cli gaon-conversation-context-release-check --db :memory:
python -m gaon.runtime.cli gaon-telegram-followup-release-check --db :memory:
python -m gaon.runtime.cli gaon-result-presentation-release-check --db :memory:
python -m gaon.runtime.cli gaon-conversational-reasoning-release-check --db :memory:
```

## Rollback

Revert the Sprint 153 commit. No schema migration is included, so rollback only
returns conversational routing/rendering to the previous Sprint 152/Hotfix 152.3
behavior.

## Completion Checklist

- [x] Main synced to Hotfix 152.3 merge commit.
- [x] Feature branch created.
- [x] Sprint 153 document created.
- [x] Intent model extended.
- [x] Explanation-level model added.
- [x] Typed reasoning dataclasses added.
- [x] Telegram path integrated.
- [x] Release check added.
- [x] Unit and integration tests added.
- [x] Full verification completed.
- [x] Documentation updated.
- [x] Commit created.
