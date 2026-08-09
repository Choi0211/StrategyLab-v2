# StrategyLab v2.1 Release Candidate Notes

Status: v2.1 Release Candidate  
Base: StrategyLab v1.0 Stable Release

## Sprint 176 Normalized Claim Bridge

Sprint 176 connects normalized source content to the existing verbatim claim and
Knowledge Candidate foundation. Gaon now checks provenance, raw content
checksum, source quality, and normalization eligibility before extracting
claims from normalized evidence.

New command:

```bash
python -m gaon.runtime.cli gaon-normalized-claim-bridge-release-check
```

The release check verifies verbatim claim extraction, unvalidated candidate
creation, source/checksum linkage, and fail-closed blocking for unsupported
normalized content. It does not validate knowledge, approve production use,
mutate strategies, promote a Champion, or trade.

## Sprint 175 Safe Source Content Normalization

Sprint 175 adds a bounded source-content normalization layer after Sprint 174
content acquisition. Gaon can now turn acquired text, HTML, and JSON evidence
into deterministic plain text while preserving acquisition provenance and
checksums.

New command:

```bash
python -m gaon.runtime.cli gaon-content-normalization-release-check
```

The release check verifies HTML script/style/navigation stripping, JSON
data-only extraction, unsupported PDF fail-closed handling, and that normalized
content is only marked eligible for later claim extraction. It does not validate
knowledge, approve production use, execute downloaded content, mutate strategy
configuration, promote a Champion, or trade.

## Hotfix 163.5 Autonomous Research Candidate Identity Integrity

Hotfix 163.5 fixes duplicate logical candidate labels in autonomous research
history. Gaon now keeps duplicate-prevention keys strict while rendering
historical candidate identity through one canonical representation,
`candidate_kind=<kind>`.

New command:

```bash
python -m gaon.runtime.cli gaon-autonomous-candidate-identity-release-check --db :memory:
```

The release check verifies that `robust-breakout` and `regime-filter` each
appear exactly once in historical and TESTED candidate history after repeated
`NO_NEW_RESEARCH_PATH` continuations. It does not enable trading, Champion
promotion, approval bypass, or strategy mutation.

## Hotfix 163.4 Autonomous Research History Integrity

Hotfix 163.4 fixes autonomous progress comparison after a
`NO_NEW_RESEARCH_PATH` continuation. Gaon now keeps root autonomous research
history separate from the empty current continuation cycle, so previously
generated and TESTED candidates remain visible in follow-up explanations.

New command:

```bash
python -m gaon.runtime.cli gaon-autonomous-research-history-release-check --db :memory:
```

The release check verifies that robust-breakout and regime-filter candidate
history remains available, the current cycle correctly reports zero new
candidates, continuation count reaches 2, and the comparison question does not
rerun tools or fabricate metric/assumption deltas. It does not enable trading,
Champion promotion, approval bypass, or strategy mutation.

## Hotfix 163.3 Autonomous Research Progression Integrity

Hotfix 163.3 fixes repeated autonomous continuation prompts. `계속 연구해줘`
now carries the previous autonomous research state into the read-only safe tool
instead of restarting from a fresh baseline. The continuation state tracks
parent/root cycle IDs, continuation count, tested candidate keys, and immutable
strategy/assumption fingerprints.

New command:

```bash
python -m gaon.runtime.cli gaon-autonomous-research-progression-release-check --db :memory:
```

The hotfix also adds grounded progress comparison rendering for prompts like
`처음 연구와 비교해서 무엇이 달라졌어?`. Gaon reports only structured
progression facts and blocks unsupported cost-assumption or performance metric
deltas. It does not enable trading, Champion promotion, approval bypass, or
strategy mutation.

## Hotfix 163.2 Autonomous Conversation Context Integrity

Hotfix 163.2 fixes presentation-only follow-ups after autonomous research and
Learning Memory summaries. A prompt such as `쉽게 설명해줘` now preserves the
semantic type of the previous answer instead of reinterpreting it as a normal
BacktestResult.

New command:

```bash
python -m gaon.runtime.cli gaon-autonomous-conversation-context-release-check --db :memory:
```

The hotfix prevents fabricated fallback fields such as unknown periods,
zero-trade metrics, or unavailable total-return calculations. It does not rerun
research tools for presentation-only follow-ups and does not enable trading,
Champion promotion, approval bypass, or strategy mutation.

## Hotfix 163.1 Telegram Autonomous Research Routing

Hotfix 163.1 connects Telegram natural-language follow-ups to the completed
autonomous research cycle. After a grounded research answer, Gaon can now route
same-chat requests for validation, critique/improvement, continuation, and
learning summaries into the deterministic read-only autonomous research path.

New command:

```bash
python -m gaon.runtime.cli gaon-telegram-autonomous-research-release-check --db :memory:
```

The response remains grounded in structured tool output. The hotfix does not
enable live trading, automatic Champion promotion, approval bypass, or strategy
configuration mutation.

## Sprint 163 Autonomous Research Completion

Sprint 163 adds the completion release check for Sprints 156 through 162. It
aggregates adaptive validation, planning, candidate generation, critic/retest,
Learning Memory integration, bounded cycle execution, and operational runtime
routing into one deterministic local verification path.

New command:

```bash
python -m gaon.runtime.cli gaon-autonomous-research-complete-release-check --db :memory:
```

Successful completion reports `AUTONOMOUS RESEARCH COMPLETE`. This status does
not enable live trading, automatic Champion promotion, strategy mutation, or
approval bypass.

## Sprint 162 Operational Autonomous Research

Sprint 162 adds a production-shaped deterministic runtime wrapper for
autonomous research requests. It enforces execute/dry-run safety gates, skips
duplicate request IDs, and renders Korean reports from structured evidence.

New command:

```bash
python -m gaon.runtime.cli gaon-operational-autonomous-research-release-check --db :memory:
```

The operational wrapper does not call an LLM provider, invent metrics, mutate
Telegram configuration, apply strategy configuration, or place orders.

## Sprint 161 Autonomous Research Cycle

Sprint 161 composes adaptive validation, planning, critic/retest, and Learning
Memory integration into a bounded autonomous research cycle. The cycle reports
terminal states such as insufficient evidence, data failure, budget exhausted,
and user approval required.

New command:

```bash
python -m gaon.runtime.cli gaon-autonomous-research-cycle-release-check --db :memory:
```

Invalid data quality fails closed. Sufficient evidence still requires user
approval before any strategy configuration change.

## Sprint 160 Autonomous Learning Memory Integration

Sprint 160 stores autonomous research outcomes as unvalidated, evidence-backed
Learning Memory records. Stored records include confidence, revalidation
metadata, and append-only audit events.

New command:

```bash
python -m gaon.runtime.cli gaon-autonomous-learning-memory-release-check --db :memory:
```

Duplicate records are reported without automatic merge. The integration does
not validate knowledge, apply policy, approve changes, or mutate strategy
configuration.

## Sprint 159 Research Critic / Improvement / Retest

Sprint 159 adds a deterministic critic loop. Gaon can now report evidence
weaknesses, propose bounded improvements, record candidate retest outcomes,
and retain rejected evidence for later review.

New command:

```bash
python -m gaon.runtime.cli gaon-research-critic-release-check --db :memory:
```

The loop remains advisory. It does not place orders, promote Champions,
approve changes, or mutate strategy configuration.

## Sprint 158 Strategy Candidate Generation

Sprint 158 adds deterministic candidate generation. Candidates carry parent
strategy, hypothesis, changed rules, rationale, supporting evidence, expected
effect, possible downside, and rollback metadata. Generated candidates are
proposals only; production strategy mutation remains disabled.

New command:

```bash
python -m gaon.runtime.cli gaon-strategy-candidate-generation-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged.

## Sprint 157 Autonomous Research Planner

Sprint 157 converts evidence gaps into deterministic autonomous research plans.
Plans contain bounded steps, priorities, dependencies, retry/runtime budgets,
and explicit stop conditions. Invalid data quality becomes a terminal data
failure rather than an execution plan.

New command:

```bash
python -m gaon.runtime.cli gaon-autonomous-research-planner-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged.

## Sprint 156 Adaptive Research Validation

Sprint 156 adds a deterministic adequacy layer for autonomous research. Gaon
now distinguishes sufficient, insufficient, degraded, and invalid evidence
using structured inputs such as trade count, observation period, regime
coverage, win/loss sample, data quality, and symbol coverage.

When evidence is insufficient, the output is a bounded validation plan. It may
recommend period expansion, other-regime testing, multi-symbol validation,
parameter robustness checks, or out-of-sample validation. It does not authorize
strategy changes, Champion promotion, knowledge validation, or orders.

New command:

```bash
python -m gaon.runtime.cli gaon-adaptive-validation-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged.

## Hotfix 155.1 Conversational Re-execution Integrity

Hotfix 155.1 fixes production follow-up reruns after multi-symbol comparison
research. The conversation layer now reads the real `multi_symbol_research`
`evidence` payload shape, validates symbol identity and structured metrics, and
fails closed instead of rendering `unknown(unknown)` if a safe-tool result is
malformed.

The hotfix also adds narrow typo tolerance for comparison follow-ups such as
`비겨해줘` and symbol typo `sk하이닏스`. Default rerun responses summarize
data-quality warnings; explicit follow-ups such as `데이터 문제 자세히 보여줘`
show stored quality evidence without rerunning research.

New command:

```bash
python -m gaon.runtime.cli gaon-conversational-reexecution-integrity-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged.

## Sprint 155 Conversational Research Execution

Sprint 155 connects explicit Telegram period-change follow-ups to authoritative
research execution. After a structured research answer, requests such as
`5년으로 다시 해봐`, `3년으로 다시 비교해줘`, or `2021년부터 지금까지 분석해줘`
reuse the same chat-scoped research context and execute existing safe tools
instead of summarizing the previous answer string.

Ambiguous requests such as `더 긴 기간으로 다시 분석해봐` ask for a concrete
period before running. Presentation-only requests such as `조금 더 짧게` still
reuse the stored structured result without rerunning research.

New command:

```bash
python -m gaon.runtime.cli gaon-conversational-research-execution-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged.

## Hotfix 154.1 Presentation State and Grounding Integrity

Hotfix 154.1 strengthens Sprint 154's presentation state handling. Explicit
current requests such as `조금 더 짧게`, `자세히 보여줘`, `전문용어 빼줘`,
and `표로 보여줘` now override stale previous style/length preference while
reusing the same authoritative structured research context.

Short and plain-language renderers preserve known source metadata such as
`Yahoo Chart 공개 데이터`; they must not degrade a known source into
unknown-source wording. Detailed follow-ups re-render from structured evidence
instead of summarizing the previous response string. MDD examples now state that
the capital calculation is illustrative.

New command:

```bash
python -m gaon.runtime.cli gaon-presentation-integrity-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged.

## Sprint 154 Natural Conversation & Teaching Engine

Sprint 154 adds a deterministic presentation layer on top of Sprint 153
reasoning. Gaon now separates what the evidence says from how the answer is
presented, with typed style, explanation-depth, and response-length contracts.

Telegram follow-ups such as `한 줄로 말해줘`, `비유해서 설명해줘`,
`예를 들어 설명해줘`, `전문적으로 설명해줘`, and `전문용어 빼줘` reuse the
existing same-chat research context instead of running research again. Teaching
responses use grounded analogies and exact numeric examples only when the
structured evidence contains the required inputs.

New command:

```bash
python -m gaon.runtime.cli gaon-natural-conversation-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged: no live
trading, no broker/KIS order, no automatic Champion promotion, no approval
bypass, no unsupported recommendation, and no strategy config mutation.

## Sprint 153 Conversational Reasoning & Explanation Engine

Sprint 153 adds a deterministic evidence-bound reasoning layer for Telegram
conversation. Gaon can now answer decision-style and explanation-style prompts
such as `삼성전자 지금 사도 돼?`, `위험은 어느 정도야?`, `쉽게 설명해줘`,
`전문적으로 설명해줘`, and `3년 기간으로 다시 해줘` while preserving the
previous structured research context.

Responses are rendered as user-facing reasoning summaries, not hidden
chain-of-thought. The default structure separates conclusion, core evidence,
limitations, risk, unsupported claims, and next validation steps. Professional
explanations include MDD, Sharpe, Profit Factor, exposure, and sample-size
reliability notes.

New command:

```bash
python -m gaon.runtime.cli gaon-conversational-reasoning-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged: no live
trading, no broker/KIS order, no automatic Champion promotion, no approval
bypass, and no strategy config mutation.

## Hotfix 152.3 Result Units and Presentation Integrity

Hotfix 152.3 makes conversational research reports preserve metric units.
`expectancy` is now rendered as a capital-denominated amount, with any
capital-relative percentage clearly derived from `initial_capital`. It is no
longer formatted as a raw percentage.

Default Telegram-facing output also hides internal strategy fingerprints,
validation IDs, run IDs, and raw provenance keys. Data quality and source
metadata are rendered with Korean labels such as `데이터 무결성 검토 통과` and
`데이터 출처: Yahoo Chart 공개 데이터`. Repeated warning prefixes are
deduplicated.

New command:

```bash
python -m gaon.runtime.cli gaon-result-presentation-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged: no live
trading, no broker/KIS order, no automatic Champion promotion, no approval
bypass, and no strategy config mutation.

## Hotfix 152.2 Telegram Follow-up Persistence and Typo Tolerance

Hotfix 152.2 makes Telegram follow-up context durable across polling ticks.
Gaon now stores the last authoritative conversational research/comparison
context in existing SQLite conversation session metadata and restores it when a
new `TelegramConversationAgent` or `LLMConversationBrain` is created.

This protects production sequences such as:

```text
삼성전자와 sk하이닉스 비교해줘
왜 그절? 판간했어?
왜 그렇게 판단했어?
쉽게 설명해줘
자세히 보여줘
```

The typo handling is intentionally narrow and only applies to follow-up
phrases. Greeting, help, status, typo, and unknown messages preserve the last
research context instead of deleting it. Comparison responses with one trade
versus zero trades remain conservative and do not claim a stable winner.

New command:

```bash
python -m gaon.runtime.cli gaon-telegram-followup-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged: no live
trading, no broker/KIS order, no automatic Champion promotion, no approval
bypass, and no strategy config mutation.

## Hotfix 152.1 Conversational Follow-up Context Integrity

Hotfix 152.1 makes Sprint 152 follow-up prompts context-safe. When a Telegram
chat asks `왜 그렇게 판단했어?`, `쉽게 설명해줘`, or `자세히 보여줘`, Gaon now
uses the immediately previous research result from that same chat/session.

If there is no prior research context, Gaon returns:

```text
직전에 설명할 분석 결과가 없습니다. 먼저 종목 분석이나 비교를 요청해 주세요.
```

and does not call unrelated tools. Comparison follow-ups preserve all compared
symbols and per-symbol warnings. `quality_status=pass` is described only as a
data-quality pass, not as strategy validity or performance confidence.

New command:

```bash
python -m gaon.runtime.cli gaon-conversation-context-release-check --db :memory:
```

No schema migration is included. Safety boundaries remain unchanged: no live
trading, no broker/KIS order, no automatic Champion promotion, no approval
bypass, and no strategy config mutation.

## Sprint 152 Gaon Conversational MVP

Sprint 152 adds a deterministic Telegram conversational MVP. Clear Korean
messages such as `안녕하세요`, `삼성전자 분석해줘`, `삼성전자와 SK하이닉스 비교해줘`,
`왜 그렇게 판단했어?`, `쉽게 설명해줘`, and `자세히 보여줘` route through a
bounded safe path.

Gaon now renders verified `krx_real_research` output as a human-readable Korean
summary with target symbol, data period, one-line conclusion, total return,
MDD, trade count, quality status, reliability warnings, risks, and next
possible actions. Internal IDs, raw fixture booleans, Python `None`, raw class
names, and raw JSON are hidden by default.

Two-symbol comparisons execute each requested symbol under the same strategy
text and assumptions. If one symbol fails, Gaon does not rank the remaining
successful symbol as if the comparison were complete.

New command:

```bash
python -m gaon.runtime.cli gaon-conversation-release-check --db :memory:
```

No schema migration is included. Sprint 152 does not add live trading,
broker/KIS orders, automatic Champion promotion, approval bypass, or strategy
configuration mutation.

## Sprint 151 Dynamic KRX Universe Selection

Sprint 151 adds a read-only dynamic KRX universe selector. It ranks an approved
provider universe snapshot by `trading_value`, breaks ties by canonical
six-digit KRX symbol, records fixture/real provenance, and returns an auditable
deterministic result.

The selector can feed the existing multi-symbol research orchestrator through a
`KRXUniverseResult`. Explicit user-provided symbols remain the highest priority
and are not silently replaced by an automatically selected universe.

New commands:

```bash
python -m gaon.runtime.cli krx-universe-select \
  --market ALL \
  --date 2026-07-30 \
  --metric trading_value \
  --size 5 \
  --json

python -m gaon.runtime.cli krx-universe-release-check
```

The release check is deterministic and fixture-backed. Production real-universe
selection is pending an approved provider universe snapshot; Yahoo historical
bars alone are not treated as a full-market universe source.

Safety boundaries are unchanged: no live trading, no broker/KIS order, no
automatic Champion promotion, no approval bypass, and no strategy config
mutation.

## Hotfix 150.5 Production Multi-Symbol Yahoo Registry Alignment

Status: COMPLETE.

Final production verification was completed on merge commit `5f6ad1d` with
implementation commit `519692c`. The deployed module is now imported from
`/opt/strategylab-v2/src/gaon/research/krx_real_pipeline.py` after reinstalling
StrategyLab v2 in editable mode and restarting `strategylab-gaon`.

The closeout root cause was deployment packaging, not research logic: the VPS
service was using a stale copied `gaon` package from
`.venv/lib/python3.12/site-packages` instead of the Git working tree under
`/opt/strategylab-v2/src/gaon`. Future deployments must run
`.venv/bin/pip install -e .` and verify `deployment-import-path-check` before
service restart verification.

Production inspection showed that Hotfix 150.4 did not fully exercise the
production-equivalent registry path. The live Yahoo data for `000660`,
`005380`, `035420`, and `051910` includes the common 2022 zero-volume anomaly
set plus symbol-specific additional dates, so the common dates remained
blocking for non-`005930` symbols.

The fix stores the common anomaly set and each symbol's additional VPS
inspection evidence, then normalizes Yahoo-style symbols before anomaly lookup.
This keeps `000660`, `000660.KS`, and `KQ:<symbol>` forms from bypassing the
same provider registry.

The KRX calendar is unchanged. `2022-01-03`, `2022-05-09`, the symbol-specific
2023 gaps, and `2025-09-19` remain exchange-open provider anomalies. Unknown
missing dates and unregistered zero-volume bars remain blocking.

## Hotfix 150.4 Yahoo Multi-Symbol Data Quality

Hotfix 150.4 extends the Yahoo KRX anomaly registry from single-symbol Samsung
verification to the Sprint 141-150 five-symbol research universe:
`005930`, `000660`, `005380`, `035420`, and `051910`.

The KRX trading calendar remains exchange-only. Missing bars on exchange-open
dates are classified as provider or symbol-specific Yahoo anomalies only when
production inspection evidence exists. The common provider gaps are
`2022-01-03` and `2022-05-09`; extra symbol-specific gaps are isolated to the
affected symbols. The verified 2022 zero-volume bars are excluded from
backtest input and disclosed as `provider_zero_volume_anomaly` warnings.
Unregistered zero-volume rows remain blocking.

No schema migration is included. The hotfix preserves all no-trading,
no-Champion-auto-promotion, no-approval-bypass, and fail-closed data-quality
boundaries.

## Hotfix 150.3 Multi-Symbol History Intent Collision

Production routing diagnostics found that the phrase `기록해줘` inside a
multi-symbol execution request was being treated as a request to read historical
research records. The router now requires explicit past/history/query semantics
before selecting `multi_symbol_research_history`.

Expected diagnostic result for the full production Telegram request:

```text
parsed_intent=multi_symbol_research
selected_route=tool_read_only_authoritative
selected_tool=multi_symbol_research
execution_intent=true
history_intent=false
status_intent=false
provider_allowed=false
generic_fallback=false
```

Verification:

```bash
python -m gaon.runtime.cli telegram-routing-debug --text-file production-request.txt --json
python -m gaon.runtime.cli telegram-multi-symbol-research-release-check --db <db>
```

## Hotfix 150.2 Production Multi-Symbol Routing Diagnostics

Production Telegram requests that include both multi-symbol research evidence
and explicit safety boundaries now keep the safety text as a constraint rather
than treating it as an unsafe order request. This prevents the conversation
runtime from falling back to the generic stock-analysis persona when the user
asks for read-only multi-symbol research.

New routing diagnostic:

```bash
python -m gaon.runtime.cli telegram-routing-debug \
  --text-file production-request.txt \
  --json
```

The diagnostic reports route/tool selection, detected KRX symbols, requested
date range, provider allowance, fallback reason, text hash, and normalization
metadata. It does not log secrets or raw Telegram configuration.

Expected production route:

`Telegram -> LLMConversationBrain -> multi_symbol_research -> deterministic Korean report`

## Hotfix 150.1 Telegram Multi-Symbol Routing

Production Telegram requests that include an explicit five-symbol KRX universe
now route to the authoritative `multi_symbol_research` safe tool instead of the
generic stock-analysis fallback. The router recognizes explicit multi-symbol
evidence such as multiple KRX codes, "여러 종목", "다중종목", "cross-symbol",
robustness, generalization, and TESTED candidate comparison.

The conversation layer extracts the bounded symbol list and date range from the
request text, executes the read-only tool first, persists run/evidence rows, and
returns the deterministic Korean report with `provider_calls=0`.

Verification:

```bash
python -m gaon.runtime.cli telegram-multi-symbol-research-release-check --db <db>
python -m gaon.runtime.cli multi-symbol-research-status --db <db> --json
python -m gaon.runtime.cli multi-symbol-research-history --db <db> --json
```

## Sprint 141-150 Multi-Symbol Autonomous Research

Gaon can now run bounded multi-symbol KRX research. A single user strategy and
one execution-assumption set are applied across an explicit or curated universe,
with per-symbol data quality, backtest evidence, candidate evidence,
cross-symbol aggregation, concentration analysis, sample confidence, and
generalization judgment.

The first production universe is explicit and bounded to:

`005930, 000660, 005380, 035420, 051910`

This is not a dynamic historical top-volume universe. Reports preserve universe
provenance so survivorship-bias assumptions are visible.

Verification:

```bash
python -m gaon.runtime.cli multi-symbol-research-release-check --db <db>
python -m gaon.runtime.cli telegram-multi-symbol-research-release-check --db <db>
```

Real Yahoo KRX VPS smoke:

```bash
GAON_REAL_MARKET_DATA_ENABLED=true GAON_MARKET_DATA_PROVIDER=yahoo-chart \
python -m gaon.runtime.cli multi-symbol-research-demo \
  --db /var/lib/strategylab/gaon-runtime.sqlite \
  --persist \
  --symbols 005930,000660,005380,035420,051910
```

## Hotfix 140.7 Yahoo KRX Zero Volume Anomaly Classification

Samsung Electronics (`005930`) 5-year Yahoo inspection identified 11
zero-volume rows where Yahoo returned `volume=0`, `trading_value=0`, and
`open=high=low=close` on KRX open dates. Those rows are now classified as
symbol-specific `provider_zero_volume_anomaly` entries for `real:yahoo-chart`.

Registered anomaly rows are excluded from backtest input and preserved as
quality warnings. Unregistered zero-volume rows remain blocking, so the release
policy stays fail-closed.

Verification:

```bash
python -m gaon.runtime.cli historical-krx-data-quality-release-check --db <db>
GAON_REAL_MARKET_DATA_ENABLED=true GAON_MARKET_DATA_PROVIDER=yahoo-chart \
python -m gaon.runtime.cli historical-krx-data-quality-inspect \
  --symbol 005930 --start 2021-07-25 --end 2026-07-24
```

## Hotfix 140.6 Historical KRX Data Quality Classification

Historical KRX daily quality now distinguishes exchange closures from
Yahoo-specific historical data anomalies over the five-year research window.
The calendar treats `2023-05-29` as a KRX closure, while `2022-01-03`,
`2022-05-09`, and `2025-09-19` remain exchange-open dates. For
`real:yahoo-chart` and `005930`, `2022-01-03` and `2022-05-09` are classified
as symbol-specific provider gaps when absent from the payload.

Zero-volume bars remain blocking unless a dated provider anomaly is registered
with evidence. The new inspection CLI reports exact zero-volume dates and raw
OHLCV details from the configured provider without persisting production state.

Verification:

```bash
python -m gaon.runtime.cli historical-krx-data-quality-release-check --db <db>
GAON_REAL_MARKET_DATA_ENABLED=true GAON_MARKET_DATA_PROVIDER=yahoo-chart \
python -m gaon.runtime.cli historical-krx-data-quality-inspect \
  --symbol 005930 --start 2021-07-25 --end 2026-07-24
```

## Hotfix 140.3 Historical KRX Trading Calendar Accuracy

KRX daily data-quality checks now use a broader historical trading calendar for
the current five-year retest horizon. The calendar keeps weekends, government
holidays, election days, Labor Day, temporary holidays, KRX-designated closures,
and year-end market closures separate from provider-specific data gaps.

For the Samsung Electronics production window `2023-07-25` through
`2026-07-24`, the deterministic historical calendar excludes the known 2023 and
2024 market closures and leaves `2025-09-19` as the only Yahoo KRX historical
provider gap. That date remains an exchange-open day and is not added as a KRX
holiday.

Verification:

```bash
python -m gaon.runtime.cli historical-krx-calendar-release-check --db <db>
python -m gaon.runtime.cli krx-trading-calendar-release-check --db <db>
python -m gaon.runtime.cli provider-gap-release-check --db <db>
python -m gaon.runtime.cli autonomous-retest-release-check --db <db>
```

Production real-provider verification:

```bash
GAON_REAL_MARKET_DATA_ENABLED=true \
GAON_MARKET_DATA_PROVIDER=yahoo-chart \
python -m gaon.runtime.cli real-krx-data-release-check \
  --db /var/lib/strategylab/gaon-runtime.sqlite \
  --symbol 005930 \
  --start 2023-07-25 \
  --end 2026-07-24
```

## Hotfix 140.2 Telegram Retest Persistence Visibility

Telegram autonomous retest runs are now visible through the same production
SQLite runtime DB used by the Telegram worker. The root cause was an overly
broad artifact filter: the `test:` marker matched the substring inside
`autonomous-retest:*`, so real production runs were persisted but hidden from
`research-retest-status` and `research-retest-history`.

The filter now excludes only explicit release-check/demo/test artifact prefixes.
Status/history payloads also expose the key lineage required for operations:
run metadata, symbol, strategy and assumptions fingerprints, period evidence,
provider gaps, blocking finding details, metrics, confidence, warnings, stop
reason, and candidate counts.

Verification:

```bash
python -m gaon.runtime.cli telegram-retest-persistence-release-check --db <db>
python -m gaon.runtime.cli research-retest-status --db /var/lib/strategylab/gaon-runtime.sqlite
python -m gaon.runtime.cli research-retest-history --db /var/lib/strategylab/gaon-runtime.sqlite
```

The release check runs isolated fixture state and must not add release-check
artifacts to production history. Real production history is created only by the
actual Telegram retest request path.

## Hotfix 140.1 Telegram Autonomous Retest Routing

Telegram natural-language requests that explicitly ask for automatic retesting,
sample sufficiency checks, or period expansion now route to the Sprint 131-140
Autonomous Retest Orchestrator before the older one-shot `krx_real_research`
path.

Recognized Korean phrases include `재검증`, `다시 검증`, `자동 재검증`,
`표본이 부족하면`, `충분한 표본`, `기간을 확장`, `더 긴 기간`, `18개월`,
`3년`, and `5년`. English phrases such as `retest`, `re-test`,
`expand period`, and `insufficient sample` are also recognized.

The Telegram path is authoritative and deterministic:

```text
Telegram text
→ LLMConversationBrain
→ research_retest safe tool
→ AutonomousRetestOrchestrator
→ deterministic Korean report
→ Telegram response
```

Provider free-form responses are not used for the final metrics. The route
preserves no-order, no-auto-promotion, no-approval-bypass, and no Telegram config
mutation boundaries.

## Sprint 131-140 Autonomous Retest Pipeline

Gaon now supports an evidence-first autonomous retest workflow for real KRX
research. When the initial result has insufficient sample size, the system can
expand the research period deterministically, re-fetch market data, re-run the
same strategy and execution assumptions, preserve period lineage, re-evaluate
tested candidates, and refresh the advisory recommendation.

Schema advances to v35 with `research_retest_runs`,
`research_retest_evidence`, and `research_period_plans`.

New CLI commands:

```bash
python -m gaon.runtime.cli research-retest-demo --db <db>
python -m gaon.runtime.cli autonomous-retest-release-check --db <db>
python -m gaon.runtime.cli research-retest-status --db <db>
python -m gaon.runtime.cli research-retest-history --db <db>
```

New read-only safe tools:

- `research_retest_status`
- `research_retest_history`

The workflow remains advisory. It does not place orders, call KIS/brokers,
promote Champions automatically, bypass approval, mutate Telegram
configuration, or apply strategy config changes.

## Hotfix 130.1 Research Operations State Isolation

Research Operations release-check and demo fixture data no longer contaminates
production research state. `research-ops-release-check --db <db>` validates the
target schema and table immutability while executing its fixture writes in an
isolated in-memory runtime store.

`research_operation_status` excludes release-check/demo/test artifacts by
default. When no real operational research report or approved config exists, it
returns the deterministic Korean message `현재 활성 연구 운영 결과가 없습니다.`

Production cleanup is available through:

```bash
python -m gaon.runtime.cli research-ops-cleanup --db /var/lib/strategylab/gaon-runtime.sqlite --dry-run
python -m gaon.runtime.cli research-ops-cleanup --db /var/lib/strategylab/gaon-runtime.sqlite --apply
```

Cleanup targets only provenance-identifiable release-check/demo/test artifacts,
records an `artifact_cleanup` audit event, and preserves real user research
state. Schema remains v34.

## Sprint 121-130 Research Operations

Gaon now has an approval-gated research operations layer for structured
Champion/Challenger research. The pipeline detects insufficient sample sizes,
caps confidence when trade count is low, recommends period expansion/re-test,
evaluates candidate dominance, and recommends a Challenger only when quality,
confidence, and dominance rules pass.

Approved strategy configuration changes are separated from Champion promotion
and live trading. A config can be applied only after explicit human approval,
and every applied change stores audit and rollback references. The read-only
`research_operation_status` safe tool can inspect operation status but cannot
approve, mutate configuration, place orders, or promote a Champion.

Schema advances to v34. Existing v33 safety boundaries remain in force.

## Hotfix 120.7 Structural Authoritative Grounding Validator

Strict real-research grounding now treats authoritative performance metrics as
structured evidence, not independent literal blacklist tokens. Reported metric
phrases are normalized to canonical fields such as `trade_count`, `wins`,
`losses`, `mdd`, `profit_factor`, and `total_return`, then compared against the
structured `BacktestResult`, tested candidate results, comparison rows, and
validation metrics.

The validator no longer allows numbers merely because they appear somewhere in
the raw output object. Metadata dates and provider-gap evidence remain allowed,
while performance values must match a metric key/value relationship. Untested
strategy conditions such as RSI, MA changes, volume multipliers, stop/take-profit
changes, and performance numbers in `HYPOTHESIS` remain fail-closed. Schema
remains v33.

## Hotfix 120.6 Authoritative Backtest Metric Grounding

Strict real-research grounding now derives allowed user-facing metric evidence
from structured authoritative results instead of fixed suspicious-token
exceptions. Backtest metrics such as `wins`, `losses`, `trade_count`, `mdd`,
`total_return`, and `profit_factor` can be rendered through Korean or internal
aliases only when the value matches the authoritative result.

The deterministic real-research renderer is self-validated before Telegram
delivery. Fabricated metrics such as a mismatched trade count, MDD, RSI,
take-profit, MA, or volume multiplier remain blocked. The Telegram strict
release check is repeatable on persistent DBs by validating that a new
`krx_real_research` audit entry is appended for the current run. Schema remains
v33.

## Hotfix 120.2 Real Provider Gap Classification

Gaon now separates exchange calendar gaps from market-data-provider gaps. The
KRX calendar remains the exchange schedule only. The known Yahoo KRX anomaly on
`2025-09-19` is classified as `provider_gap` for `real:yahoo-chart` and is not
added as a KRX holiday.

Real-data release checks now allow provider-gap-only warnings while continuing
to block unknown missing trading days, malformed OHLCV, duplicates, and other
non-allowlisted quality findings. Korean research reports disclose provider
gaps instead of hiding them.

## Hotfix 120.1 KRX Trading Calendar Quality

KRX daily market-data quality checks now evaluate missing bars against trading
dates instead of raw calendar dates. Weekends and bounded deterministic KRX
non-trading dates are not counted as `missing_dates`, while actual missing
trading bars, duplicate bars, malformed OHLCV, and stale data continue to be
reported.

The new `krx-trading-calendar-release-check` verifies the calendar policy
without live network access. Schema remains v33.

## Real KRX Data Activation

Gaon can now activate a real public historical market data provider for
KRX-listed symbols. The first provider is `real:yahoo-chart`, which maps Korean
symbols such as `005930` to public Yahoo chart symbols such as `005930.KS` and
parses daily OHLCV data into the existing MarketDataset contract.

Real activation is explicit. Production must set
`GAON_REAL_MARKET_DATA_ENABLED=true` and
`GAON_MARKET_DATA_PROVIDER=yahoo-chart`. Without those settings, CI and local
release checks continue to use fixture data and disclose `source=fixture`.

Provider failures, empty responses, malformed responses, and failed data
quality checks fail closed as `real_data_unavailable`; fixture results are not
substituted.

## Sprint 111-120 KRX Real Research Pipeline

Gaon now has a read-only KRX real-research pipeline foundation. Korean strategy
requests can be parsed into provenance-aware StrategySpec records, run through
source-aware KRX-shaped datasets, deterministic rule backtests, walk-forward
validation, evidence-based critique, bounded improvement candidate generation,
candidate comparison, research memory persistence, and a Korean report.

Tests and default local release checks use explicitly marked `source=fixture`
data. The production real-data release check uses the configured public provider
and reports `real_data_unavailable` instead of silently substituting fixture
data when real data cannot be retrieved or validated.

Not included: live trading, broker orders, automatic Champion promotion,
approval bypass, arbitrary shell/SQL, LLM-generated Python execution, secret
exposure, private repository dependency, or automatic production deployment.

## Hotfix 110.2 Korean Response Language Consistency

When Youngha asks in Korean, Gaon's final Telegram-facing response is now normalized to Korean. Internal provenance keys such as `fixture_backed=true` and `validation_backend=fixture` remain intact, while explanations, critic findings, improvement suggestions, missing-data messages, and fallback text are Korean.

Provider wrapper tags such as `<output>` and `<response>` are removed before final response persistence. If a provider returns an English final answer for a Korean research tool request, Gaon falls back to deterministic grounded Korean formatting from the safe-tool result.

Not included: live trading, broker orders, automatic Champion promotion, approval bypass, shell or SQL expansion, secret exposure, or schema migration.

## Hotfix 110.1 Research Grounding Context Isolation

Gaon now separates user-provided strategy conditions from fixture/default candidate metadata before producing Telegram research critique responses. Provider-backed tool synthesis receives sanitized research payloads, so default fixture parameters and regime metadata are not described as current user strategy values.

Quality-score requests without an actual stored backtest-based result now return a Korean deterministic missing-data response and suggest running an actual data backtest first. No schema migration is included.

Not included: live trading, broker orders, automatic Champion promotion, approval bypass, shell or SQL expansion, secret exposure, or private repository access.

## Hotfix Research Grounding and Telegram Routing

Gaon now grounds Telegram research answers in verified safe-tool output and explicit user-provided facts. Strategy weakness, improvement, memory search, quality-score, data-quality, and backtest requests route to read-only safe tools before free-form synthesis.

Fixture-backed data is disclosed as `fixture_backed=true`. Empty research memory is reported as no stored match, not as a system access failure. This release check is repeatable against persistent SQLite databases through unique run namespaces.

Not included: live trading, broker orders, automatic Champion promotion, automatic approval, private repository access, schema migration, or external paid-provider fallback.

## Sprint 56-60 LLM Agent Release

Gaon now supports a generic OpenAI-compatible provider interface, native read-only tool calling, bounded multi-turn context, safe agent planning, and release diagnostics. The release remains independent of private repositories and does not add live KIS, broker orders, automatic approval, arbitrary shell, arbitrary SQL, secret access, mandatory Ollama, or paid-provider fallback.

## Sprint 51-55 Conversational Release

Gaon now has a persistent conversational brain foundation for StrategyLab v5. It stores conversation history, builds bounded verified context, exposes read-only tools through a deny-by-default policy, and connects Telegram ordinary text to the persistent brain.

This release does not add live trading, MyMoneyGuard access, broker orders, arbitrary shell or SQL tools, automatic approval, required Ollama, or required paid provider fallback.

## Sprint 47 Strategy Execution Runtime

Included:

- `strategy_execution_policy_v1`
- `DISABLED`, `PAPER`, and `LIVE` execution modes
- default `DISABLED` mode
- active Champion version and fingerprint binding
- PAPER execution through the existing paper adapter stack
- LIVE planning gates using Paper Revalidation status
- runtime schema v18
- events, metrics, CLI commands, unit tests, and integration tests

Not included:

- KIS adapter
- live broker orders
- live execution enablement
- automatic Champion promotion
- automatic rollback
- automatic approval
- MyMoneyGuard dependency

## Sprint 46 Paper Revalidation and Kill/Rollback Gates

Included:

- `paper_revalidation_policy_v1`
- `LIVE_ELIGIBLE`, `HOLD`, `KILL`, `ROLLBACK_RECOMMENDED`, and `REVIEW`
- paper session, summary, active Champion fingerprint, and evidence consistency gates
- runtime schema v17
- events, metrics, CLI commands, unit tests, and integration tests

Not included:

- live trading enablement
- KIS adapter
- broker orders
- automatic Champion rollback
- automatic Champion Registry mutation
- automatic approval
- MyMoneyGuard dependency

## Sprint 45 Paper Trading Forward Test

Included:

- paper-only forward-test sessions for the active Champion
- `paper_forward_test_policy_v1`
- session lifecycle: pending, active, paused, completed, failed, cancelled
- simulated paper order observations using the existing paper adapter stack
- deterministic performance summaries without fabricated unavailable metrics
- runtime schema v16
- events, metrics, CLI commands, unit tests, and integration tests

Not included:

- live KIS
- broker credentials
- real orders
- paper-to-live automatic promotion
- automatic Champion changes from paper results
- automatic approval
- MyMoneyGuard dependency

## Sprint 44 Champion Registry and Approval Promotion

Included:

- runtime schema v15 for Champion registry, history, promotion requests, and promotion decisions
- explicit first Champion bootstrap
- promotion request creation only from Sprint 43 `promotion_candidate` evaluations
- explicit approval and rejection workflow
- active Champion registry update after approval only
- immediate previous Champion rollback with preserved history
- events, metrics, CLI inspection, unit tests, and integration tests

Not included:

- automatic Champion promotion
- direct `PROMOTION_CANDIDATE` activation
- active strategy switching
- Paper Trading forward-test sessions
- live KIS
- broker credentials
- real orders
- automatic trading
- automatic approval
- MyMoneyGuard integration

## Sprint 43 Champion / Challenger Evaluation Engine

Included:

- runtime schema v14 for Champion / Challenger evaluation requests and reports
- deterministic `champion_challenger_policy_v1`
- structured request, policy, comparison, report, decision, and role contracts
- validation status hard gate using Sprint 42 `ValidationReport`
- fingerprint existence and difference gates
- return improvement gate using percentage-point improvement
- MDD degradation gate using Sprint 42 positive-fraction convention
- profit factor comparison when both values exist
- sample period and trade count explainability
- persistence, events, metrics, CLI inspection, and bounded Executive Planner / Research Agent route

Not included:

- automatic Champion promotion
- active strategy switching
- live KIS
- broker credentials
- real orders
- automatic trading
- automatic approval
- MyMoneyGuard integration
- arbitrary shell execution
- paid-provider fallback

`PROMOTION_CANDIDATE` is not `PROMOTED`.

## Sprint 42 Strategy Validation Engine

Included:

- runtime schema v13 for validation requests and validation reports
- deterministic validation contracts: `ValidationRequest`, `ValidationPolicy`, `ValidationRule`, `ValidationRuleResult`, `ValidationReport`, `ValidationStatus`, `ValidationSeverity`, and `ValidationEvidence`
- `validation_policy_v1` with conservative defaults for trade count, maximum drawdown, profit factor, sample duration, and fingerprint completeness
- MDD normalization to a documented positive-fraction convention
- optional metric handling without fabrication
- multi-run aggregation for passing window ratio and catastrophic window detection
- non-ML overfitting heuristic warnings
- lifecycle events, metrics, persistence, CLI inspection, Research Agent integration, and Executive Planner validation routing

Not included:

- Champion ranking
- Challenger ranking
- Champion promotion
- active strategy switching
- parameter optimization
- paper trading promotion
- live KIS
- broker orders
- automatic trading
- automatic approval
- MyMoneyGuard integration
- live market data
- network calls
- paid-provider fallback

Validation PASS does not automatically promote or deploy a strategy.

## Sprint 41 v1 Backtest Adapter Foundation

Included:

- runtime schema v12 for backtest requests and normalized results
- structured BacktestRequest, BacktestStrategyRef, BacktestDatasetRef, BacktestPeriod, BacktestExecutionContext, BacktestResult, BacktestMetrics, BacktestTradeSummary, and BacktestStatus models
- BacktestAdapter contract
- deterministic FakeBacktestAdapter
- LocalProcessBacktestAdapter boundary for a future fixed v1 entrypoint with JSON request/response
- normalized v1 result conversion with optional metrics, warnings, errors, engine version, duration, parameters, dataset reference, and reproducibility metadata
- stable fingerprint generation for future validation and Champion/Challenger comparison
- SQLiteBacktestRepository, BacktestExecutionService, lifecycle events, metrics, CLI commands, and tests
- bounded Executive Planner to Research Agent to BacktestAdapter flow

Not included:

- real v1 engine dependency in automated tests
- Champion/Challenger ranking
- strategy promotion
- active strategy switching
- paper trading promotion
- live strategy deployment
- KIS integration
- MyMoneyGuard integration
- automatic trading
- automatic approval
- arbitrary shell execution
- network calls
- private repository dependency

## Sprint 40 Trading Adapter Foundation

Included:

- runtime schema v11 for trading requests and simulation results
- structured TradingIntent, TradingAction, OrderSide, OrderType, TradingRequest, TradingDecision, TradingExecutionContext, TradingResult, TradingStatus, AccountSnapshot, and PositionSnapshot models
- TradingRiskPolicy guardrails for quantity, symbol format, max notional, max position, duplicate request, unsupported order type, disabled adapter, and live execution blocking
- FakeTradingAdapter compatibility and deterministic PaperTradingAdapter
- TradingExecutionService with structured errors, no-crash failure isolation, durable events, metrics, and persistence
- Executive Planner and Agent Dispatcher route for paper trading simulation
- CLI commands for `trading-status`, `trading-account`, `trading-positions`, `trading-simulate-buy`, `trading-simulate-sell`, `trading-cancel-simulated-order`, and `trading-history`

Not included:

- live trading
- KIS REST
- KIS WebSocket
- broker authentication
- real account access
- real balance query
- real order execution
- automatic trading
- automatic approval
- MyMoneyGuard integration
- live market data
- Telegram trading commands
- paid-provider fallback
- unrestricted shell execution

## Sprint 39 Daily Research Pipeline

Included:

- runtime schema v10 for daily research profiles and runs
- daily research profile creation, enable, disable, list, and show workflows
- Sprint 38 scheduler integration without adding a second scheduler
- due execution with disabled profile skip, duplicate run protection, bounded failure isolation, durable state, events, and metrics
- deterministic ResearchRequest to planner to bounded evidence search to context builder to synthesis to report flow
- markdown and json report output
- pending-review KnowledgeProposal persistence without trusted knowledge promotion
- CLI commands for `daily-research-create`, `daily-research-list`, `daily-research-show`, `daily-research-enable`, `daily-research-disable`, `daily-research-run`, and `daily-research-report`

Not included:

- Telegram delivery
- email delivery
- Notion synchronization
- GitHub polling
- live market data
- Trading Adapter execution
- broker, KIS, or MyMoneyGuard access
- external AI provider calls
- vector DB or embeddings
- automatic knowledge approval
- automatic policy change
- shell or plugin execution

## Sprint 38 Scheduler Automation

Included:

- runtime schema v9 for scheduled automation jobs and runs
- durable scheduled job creation, enable, disable, lookup, list, and due detection
- bounded scheduled execution through Executive Planner and Agent Dispatcher
- disabled-job skip, duplicate run protection, bounded retry, blocked approval-required flow, and failure isolation
- scheduled lifecycle durable events and runtime metrics
- deterministic schedule CLI smoke commands

Not included:

- Daily Research topic logic
- morning market report business logic
- Telegram delivery
- GitHub polling automation
- Notion synchronization
- Trading Adapter execution
- KIS connection
- broker orders
- automatic trading
- automatic approval
- unrestricted shell execution
- unrestricted filesystem mutation
- arbitrary plugin loading

## Sprint 37 Multi-Agent Execution Framework

Included:

- common bounded agent contracts
- explicit agent registry
- ExecutivePlan-consuming dispatcher
- deterministic ResearchAgent, CodingAgent, and MemoryAgent
- non-executing TradingAgent placeholder
- capability validation
- approval-required blocking
- failure isolation
- durable lifecycle events
- runtime metrics
- deterministic `agent-run` CLI smoke

Not included:

- scheduler execution
- cron or daily research automation
- Telegram-triggered agent execution
- broker or KIS execution
- automatic trading
- automatic approval
- arbitrary shell execution
- unrestricted filesystem mutation
- arbitrary plugin loading

## Sprint 36 Executive Planner

Included:

- immutable executive request and plan contracts
- deterministic routing for research, memory, runtime status, human review, and unsupported requests
- provider-backed routing through the existing Assistant Provider Registry
- free-only and paid-provider guardrails
- approval-required flag support
- durable event helper, runtime metrics, CLI plan inspection, unit tests, and integration tests

Not included:

- multi-agent execution
- scheduler execution
- trading adapter execution
- Telegram integration
- automatic approval

## Gaon Phase B v3.0 Research Brain RC

Included:

- Sprint 30 validated research planning with deterministic and provider-backed plan contracts
- Sprint 31 safe evidence provider contracts with fake, fixture, RSS/Atom, and disabled optional web providers
- Sprint 32 evidence ranking, citation assignment, context budgeting, and contradiction preservation
- Sprint 33 evidence-backed knowledge proposals stored separately from trusted knowledge
- Sprint 34 auditable research approval workflow with stale proposal and replay protection
- Sprint 35 Research Brain v3 orchestration, run states, checkpoints, reports, resume, CLI smoke paths, schema v8, and free-only runtime defaults

Not included:

- live broker, KIS, account, or MyMoneyGuard integration
- live Telegram, Notion, GitHub, OpenAI, Claude, Gemini, or paid provider calls in automated tests
- automatic trusted knowledge promotion
- automatic policy update
- automatic approval or trading execution

## Gaon Phase A v2.1

Included:

- assistant provider registry and deterministic fallback routing
- explicit plugin lifecycle management
- internal metrics and observability
- durable event store and safe replay
- long-term memory namespace/lifecycle foundation
- runtime service integration and event replay dry-run CLI

This release candidate is not production trading ready.

## Sprint 18-23 Production Hardening

Included:

- HMAC-SHA256 approval token digest storage and single-use approval consumption
- SQLite runtime repository layer and schema v2 migration
- schema v3 durable queue, durable scheduler, idempotent duplicate guard, and recovery contracts
- controlled runtime service loop with readiness, graceful stop, bounded drain, CLI run/status/backup, and redacted structured logs
- security and chaos tests for replay, tampering, prompt injection as data, provider failure, duplicate storms, restart recovery, scheduler idempotency, log redaction, and backup restore
- broker-free TradingAdapter protocol, risk-gate contracts, fake adapter tests, and v1 rollout plan

Not included:

- live Telegram daemon verification
- live OpenAI provider verification
- live Notion synchronization verification
- live broker verification
- private MyMoneyGuard integration
- automatic trading or approval

## Gaon Runtime Collaboration

Included:

- runtime configuration with secret masking
- deterministic in-process event bus
- deterministic Korean Conversation Runtime
- Sprint 13 natural-language intent router and Gaon persona layer
- Sprint 14 read-only memory-aware conversation context
- Assistant Provider interface for future LLM providers without SDK or network implementation
- Sprint 15 guarded assistant provider integration with deterministic fallback and OpenAI-compatible fake-transport tests
- Sprint 16 guarded research orchestration with explicit approval gates and in-memory queue
- Sprint 17 SQLite runtime state, health checks, service skeleton, backup helper, and VPS deployment docs
- Telegram production smoke client and dry-run adapter
- Telegram one-shot smoke commands for bot metadata, chat discovery, smoke send, and poll-once processing
- Notion dry-run mapper and sync contracts
- notification engine
- daily report and weekly review contracts
- in-memory scheduler
- safe dry-run CLI
- Learning Memory claims snapshot and retrieval hardening

Not included:

- long-running Telegram daemon or webhook server
- offset persistence storage
- real Notion network execution
- real LLM provider connection
- market data, calendar, stock analysis, or Telegram-triggered backtest execution
- automatic Learning Memory mutation from conversation
- external AI API
- vector DB or embeddings
- MyMoneyGuard/KIS access
- live trading
- automatic approvals

## Sprint 12-B Learning Memory Repository

Sprint 12-B adds deterministic repository and detection contracts for Learning Memory.

Included:

- `LearningRepository` protocol
- `InMemoryLearningRepository`
- duplicate candidate detection without automatic merge
- conflict candidate detection without automatic resolution
- chronological lookup
- project/strategy/market AND filters
- append-only audit workflow
- KnowledgeApproval and PolicyApproval scope matching
- ISO 8601 UTC timestamp validation
- golden JSON and migration compatibility fixtures
- related-memory retrieval with score breakdown
- repository JSON export/import
- explicit v0 to v1 migration path
- Research Brain conversion and no-auto-save memory preparation
- separate `PreferenceApproval`

Not included:

- real DB
- vector DB
- embedding or related-memory ranking
- external AI API
- Telegram or Dashboard runtime
- MyMoneyGuard access
- live trading

## Sprint 12-A Learning Memory Contracts

Sprint 12-A adds domain contracts only.

Included:

- LearningRecord
- KnowledgeClaim
- ResearchOutcome
- FailurePattern
- SuccessPattern
- UserPreference
- ConversationSummary
- ConfidenceScore
- LearningProposal
- PolicyRevision
- RevalidationSchedule
- KnowledgeApproval
- PolicyApproval
- AuditEvent

Not included:

- search engine
- real DB
- vector DB
- external AI API
- Telegram or Dashboard runtime
- MyMoneyGuard access
- live trading

## Sprint 11 Development Start

Sprint 11 starts the Gaon Research Brain and Learning Memory foundation.

Included in Sprint 11 start:

- Gaon Development Contract v1.0.
- `gaon.learning` package boundary.
- Learning Memory evidence rules.
- Knowledge lifecycle and user approval rule for `Validated`.
- Policy update candidate approval and rollback metadata.
- ADR/RFC documentation for Learning Memory core.
- Research Brain contracts for evidence-backed goals, plans, sessions, interviews, and journals.
- Research Brain hardening for session transitions, pending interview answers, and versioned JSON round-trip serialization.

## Included

- Blueprint and sprint governance.
- Public/private separation policy.
- Core project foundation.
- Market data contracts and validation.
- Strategy parameter and signal framework.
- Deterministic backtest contracts.
- Portfolio accounting foundation.
- Risk metric foundation.
- AI review schema foundation.
- Dashboard view model foundation.
- Safe broker interface and paper adapter.
- End-to-end integration test from market fixture through strategy, portfolio sizing, risk validation, backtest, and paper broker fill.
- GitHub Actions verification on Ubuntu and Windows with Python 3.11 and 3.12.

## Not Included

- Live trading.
- Real broker API credentials.
- Private MyMoneyGuard access.
- Production deployment.
- Full optimizer.

## Verification

Run:

```bash
PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit
PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration
python scripts/verify_release.py
```
# Sprint 48

StrategyLab can now generate a portable handoff package from an active Champion
and a LIVE_ELIGIBLE paper revalidation report. The generated package requires
explicit human approval before deployment eligibility.

# Sprint 49

StrategyLab can now plan and run an approval-gated deployment workflow against
generic deployment adapters. Public tests use fake and local-safe adapters only;
private production integration remains outside this repository.

# Sprint 50

Gaon v5.0 RC completes the first bounded end-to-end StrategyLab system pipeline.
It remains approval-gated, broker-free in public tests, and independent of any
private repository.

# Sprint 50 Hotfix

`v5-demo --dry-run` now creates a unique default pipeline run id and namespaces
demo fixture entities so repeated runs against the same persistent DB do not
collide with `v5-release-check` or prior demos.

# Sprint 61-70

Gaon now has a bounded External Intelligence and Autonomous Strategy Research
foundation. The release adds read-only external research tools with citation and
freshness metadata, safe URL validation, structured data tool contracts, and a
strategy research workflow that can create challenger experiments, run fixture
backtests, validate results, compare them with the Champion baseline, and write
an advisory report.

This is autonomous research, not autonomous trading. It does not place orders,
promote Champions, bypass approvals, access secrets, or use private
repositories. External content remains untrusted data.

# Sprint 71-80

Gaon now has an AI Quant Researcher foundation. It can read fixture-backed KRX
market data, score news, analyze themes and investor flow, generate candidate
strategies, run bounded fixture backtests, compare performance against a
Champion baseline, improve weaker candidates, evolve top candidates, and write
an advisory research report.

The release remains research-only. No broker order, automatic trading,
automatic Champion promotion, approval bypass, secret access, or private
repository dependency is introduced.

# Sprint 81-90

Gaon now has an AI Quant Scientist foundation. It can discover deterministic
features from fixture-backed KRX market data, rank feature importance, run
walk-forward validation, perform Monte Carlo robustness scoring, classify market
regimes, select a meta strategy, optimize an advisory portfolio mix, combine
votes through an ensemble decision, explain the recommendation, and persist an
AI Scientist report.

The release remains advisory. It does not place orders, promote Champions,
bypass approvals, access secrets, or depend on a private repository. Feature
source, trust, and freshness metadata are preserved from the underlying market
fixture.

# Hotfix 90.1

Gaon now handles longer Telegram-facing LLM responses more reliably. The
OpenAI-compatible provider records `finish_reason`, treats `length` as
truncation, requests bounded continuations, and preserves valid partial output
if a continuation fails.

Telegram delivery now chunks long plain-text responses below the API limit,
labels multi-part messages with `[n/m]`, preserves the original payload text,
and retries transient send failures with bounded backoff. The hotfix does not
add live trading, broker integration, automatic Champion promotion, approval
bypass, shell execution, arbitrary SQL, private repository access, or paid
provider fallback.

# Hotfix 90.2

`long-response-release-check` now creates a unique run namespace for every
invocation. Repeated checks against the same persistent runtime database no
longer collide on `conversation_messages.message_id`, and schema v30 remains
unchanged.

# Sprint 91-100

Gaon now has a Self-Improving Quant Researcher foundation. It can critique
strategy research results, map findings into traceable improvement actions,
iterate revised strategy candidates within a bounded loop, track lineage, store
research memory, score quality, run a candidate tournament, and produce an
autonomous research result.

The release is deterministic and advisory. It does not modify Python code,
shell out, run arbitrary SQL, change VPS configuration, place broker orders,
promote Champions, bypass approvals, or mutate private MyMoneyGuard state.

# Sprint 101-110

Gaon now has a production-grade contract foundation for real market research
and external backtest integration. It can resolve fixture-backed market
datasets, validate data quality, cache dataset metadata, build canonical
StrategySpec payloads, create versioned BacktestRequest JSON, normalize
BacktestResult payloads, compare reproducibility conditions, and run the Real
Research Gateway.

Real providers and private backtest engines are not hard-coded in this public
repository. The current implementation remains fixture-backed by default and
records `fixture_backed=true` in report provenance.

# Hotfix 120.3

Gaon now treats structured real KRX research results as authoritative when
writing user-facing Korean research reports. If an LLM provider returns
ungrounded trade counts, win/loss counts, returns, drawdowns, stop/risk
settings, or candidate parameters that are not present in the structured
`BacktestResult`, user strategy, execution assumptions, or tested candidates,
the final answer is replaced with a deterministic grounded report.

The report separates user-provided strategy conditions, engine/default
execution assumptions, tested candidates, hypothesis-only follow-up ideas, and
provider data gaps such as the Yahoo KRX `2025-09-19` missing bar. The hotfix
does not change schema v33 and does not add trading, broker access, approval
bypass, shell execution, arbitrary SQL, or generated Python execution.

# Hotfix 120.4

Telegram production-equivalent real KRX research requests now take the
authoritative safe-tool path:

`Telegram update -> TelegramRuntime -> TelegramConversationAgent -> LLMConversationBrain -> krx_real_research -> deterministic Korean renderer -> Telegram send`.

For requests such as "삼성전자 실제 데이터로 ... 백테스트 ... 개선 후보까지 비교",
Gaon executes the read-only `krx_real_research` tool before asking an LLM
provider for free-form text. Provider-generated performance numbers are not
allowed to become the final Telegram answer. If a provider tool-result
roundtrip is used elsewhere, the final text is validated against the structured
payload and replaced with the deterministic report when it contains
ungrounded metrics.

The new `telegram-strict-real-research-release-check` injects a provider that
tries to fabricate `5.32%`, `1.77%`, `MDD 8`, `거래 횟수 4회`, `RSI(14) 30`,
`MA15/MA90`, and `1.5x`. The final Telegram response must instead report the
authoritative structured result, including `trade_count=3`, `fixture_backed=false`,
and `provider=real:yahoo-chart`.

# Hotfix 120.5

Telegram research failures are now classified before they reach the user. A
market data outage, data quality blocker, backtest execution failure, generic
tool failure, actual provider timeout, and unexpected internal exception each
produce a distinct Korean response. Only an actual provider timeout uses the
local LLM delay message.

The Telegram agent records server-side traceback through `logger.exception`
with bounded metadata (`error_type`, `failure_stage`, `route`) and increments
`gaon_telegram_conversation_failures_total` with `error_type` and
`failure_stage`. It does not log bot tokens, prompts, chat payloads, or secrets.
The Telegram response does not expose Python exception text or stack traces.

Authoritative `krx_real_research` failures remain fail-closed. If market data
or backtest execution fails, Gaon returns the classified error message and does
not ask the provider to invent a replacement research report.

# Hotfix 140.7.1

Gaon now declares the first-party `tzdata` package as a runtime dependency.
This keeps IANA timezone lookups such as `Asia/Seoul` available on Windows
GitHub Actions and Windows user installations, while preserving the existing
`ZoneInfo` semantics used by Yahoo KRX diagnostics.

No schema migration is included. Hotfix 140.7 zero-volume anomaly handling
remains unchanged: only evidence-backed provider anomalies are excluded and
reported as warnings; unregistered zero-volume bars remain fail-closed.
