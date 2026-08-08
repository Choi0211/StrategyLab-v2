# Changelog

## Hotfix 163.2 - Autonomous Conversation Context Integrity

- Added distinct autonomous conversation context kinds for autonomous cycles, continuation, critique, and Learning Memory summaries.
- Added autonomous presentation renderers so `쉽게 설명해줘` and related presentation-only follow-ups preserve the prior autonomous or Learning Memory semantic context.
- Blocked fallback from Learning Memory summaries into the normal BacktestResult renderer, preventing fabricated unknown periods, zero trades, or unavailable metrics.
- Added `gaon-autonomous-conversation-context-release-check`.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Hotfix 163.1 - Telegram Autonomous Research Routing

- Added `autonomous_research_cycle` as a read-only safe tool route for Telegram conversational follow-ups.
- Routed explicit validation, critique/improvement, continuation, and learning-memory prompts from the same-chat authoritative research context into the autonomous research cycle.
- Added deterministic Korean autonomous research rendering with baseline metrics, planner steps, critic findings, candidate retest counts, and Learning Memory status.
- Added cross-chat isolation and presentation-only no-rerun regression coverage.
- Added `gaon-telegram-autonomous-research-release-check`.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Sprint 163 - Autonomous Research Completion

- Added an end-to-end completion release check aggregating Sprints 156 through 162.
- Added `AUTONOMOUS RESEARCH COMPLETE` status for deterministic local verification.
- Added `gaon-autonomous-research-complete-release-check` plus unit and integration coverage.
- Preserved schema v36, no provider-based reasoning, no automatic approval, no strategy configuration mutation, no Champion promotion, and no trading.

## Sprint 162 - Operational Autonomous Research

- Added an execute-gated deterministic operational wrapper for autonomous research requests.
- Added duplicate request protection and dry-run safety blocking before research execution.
- Added Korean structured operational reporting without LLM provider calls or fabricated metrics.
- Added `gaon-operational-autonomous-research-release-check` plus unit and integration coverage.
- Preserved schema v36, no Telegram configuration mutation, no strategy configuration mutation, no Champion promotion, and no trading.

## Sprint 161 - Autonomous Research Cycle

- Added bounded autonomous research cycle orchestration across validation, planning, critic/retest, and Learning Memory integration.
- Added explicit cycle terminal states for completed, insufficient evidence, data failure, budget exhausted, safety stop, and user approval required.
- Added fail-closed handling for invalid evidence quality.
- Added `gaon-autonomous-research-cycle-release-check` plus unit and integration coverage.
- Preserved schema v36, no automatic approval, no strategy configuration mutation, no Champion promotion, and no trading.

## Sprint 160 - Autonomous Learning Memory Integration

- Added unvalidated evidence-backed Learning Memory integration for autonomous research outcomes.
- Added append-only audit event creation for stored autonomous research memory records.
- Added duplicate reporting without automatic merge or overwrite.
- Added `gaon-autonomous-learning-memory-release-check` plus unit and integration coverage.
- Preserved schema v36, no knowledge validation, no policy application, no trading, no Champion promotion, and no strategy configuration mutation.

## Sprint 159 - Research Critic / Improvement / Retest

- Added structured critic findings for sample-size, drawdown, and data-quality issues.
- Added improvement proposals and candidate retest records that preserve supporting evidence.
- Retained rejected candidates in critic/retest reports instead of discarding negative evidence.
- Added `gaon-research-critic-release-check` plus unit and integration coverage.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Sprint 158 - Strategy Candidate Generation

- Added evidence-backed strategy candidate contracts with parent strategy, hypothesis, changed rules, rationale, expected effect, downside, and rollback metadata.
- Added deterministic candidate generation from validation plans while keeping candidates in `PROPOSED` state.
- Added `gaon-strategy-candidate-generation-release-check` plus unit and integration coverage.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no production strategy mutation.

## Sprint 157 - Autonomous Research Planner

- Added deterministic autonomous research planning contracts for goals, plans, steps, priorities, budgets, dependencies, and stop conditions.
- Converted Sprint 156 validation needs into bounded ordered research steps with retry/runtime limits.
- Added terminal data-failure planning when evidence quality is invalid.
- Added `gaon-autonomous-research-planner-release-check` plus unit and integration coverage.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Sprint 156 - Adaptive Research Validation

- Added evidence adequacy contracts and deterministic adaptive validation for trade count, observation period, regime coverage, win/loss sample, data quality, and symbol coverage.
- Added validation needs for period expansion, other-regime testing, multi-symbol validation, parameter robustness, and out-of-sample testing.
- Added fail-closed `INVALID` handling for blocking data quality without authorizing strategy mutation.
- Added `gaon-adaptive-validation-release-check` plus unit and integration coverage.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Hotfix 155.1 - Conversational Re-execution Integrity

- Fixed conversational multi-symbol reruns to normalize the production `multi_symbol_research` `evidence` schema instead of relying only on the legacy `symbols` summary shape.
- Added fail-closed validation for successful research tool results that lack authoritative symbol identity or structured metrics, preventing `unknown(unknown)` presentation.
- Added narrow typo tolerance for `비겨` comparison follow-ups and `sk하이닏스` symbol mentions.
- Changed default re-execution reports to summarize data-quality warnings while keeping detailed stored evidence available through explicit quality-detail follow-ups.
- Added `gaon-conversational-reexecution-integrity-release-check` plus unit and Telegram integration coverage for period parsing, typo normalization, production-equivalent multi-symbol schema handling, quality-detail follow-ups, and invalid-result blocking.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Sprint 155 - Conversational Research Execution

- Added immutable `ConversationalResearchExecutionRequest` and `ConversationalResearchExecutionResult` contracts for chat-scoped research reruns.
- Added deterministic period resolution for explicit `3년`, `5년`, recent-year, and year-start requests while keeping ambiguous period changes fail-closed.
- Wired `krx_real_research` safe tool arguments for `start_date` and `end_date`.
- Added Telegram conversation routing that reuses previous structured strategy context and assumptions for single-symbol reruns.
- Added multi-symbol period reruns through `multi_symbol_research` when the previous context was a comparison.
- Kept presentation-only follow-ups isolated so requests like `조금 더 짧게` do not rerun research.
- Added `gaon-conversational-research-execution-release-check` plus unit and Telegram integration coverage for context resolution, period resolution, multi-symbol execution, missing-context handling, and metadata hiding.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Hotfix 154.1 - Presentation State and Grounding Integrity

- Added `PresentationFormat` to make prose, bulleted detail, and table presentation intent explicit.
- Strengthened preference precedence so the current user message overrides stale short/plain/professional state.
- Preserved authoritative source metadata in short/plain presentation renderers.
- Made detailed follow-ups re-render from structured context even after prior one-line or short follow-ups.
- Clarified MDD examples as illustrative applications of MDD to initial capital, not realized cash-loss claims.
- Added `gaon-presentation-integrity-release-check` plus unit and Telegram integration coverage for source preservation, single-renderer behavior, detail-after-short behavior, and no research rerun.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Sprint 154 - Natural Conversation & Teaching Engine

- Added deterministic natural presentation on top of Sprint 153 evidence-bound reasoning.
- Added typed immutable presentation contracts: `ConversationStyle`, `ExplanationDepth`, `ResponseLength`, `ConversationPresentationRequest`, `ConversationPresentationResult`, `PresentationPreference`, `Analogy`, and `ExampleCalculation`.
- Added session-scoped Telegram presentation preference for concise, conversational, explanatory, teaching, professional, and report styles.
- Added grounded teaching analogies and exact MDD example calculations without adding unsupported metrics or investment recommendations.
- Added `gaon-natural-conversation-release-check` plus unit and Telegram integration coverage for direct-answer-first rendering, one-line responses, teaching examples, professional terminology, context reuse, metadata suppression, and recommendation guard behavior.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Sprint 153 - Conversational Reasoning & Explanation Engine

- Added deterministic conversational reasoning intents for investment-decision questions, risk questions, strategy questions, professional explanations, timeframe/rerun requests, recommendation requests, and contextual follow-ups.
- Added typed immutable reasoning contracts: `ConversationReasoningRequest`, `ConversationReasoningResult`, `EvidencePoint`, `Limitation`, `RiskPoint`, `NextAction`, `ExplanationLevel`, and `DecisionBoundary`.
- Added evidence-bound Korean renderers that separate conclusion, core evidence, limitations, risk, unsupported claims, and next validation steps without exposing chain-of-thought.
- Added recommendation and investment-decision guards so insufficient samples never become buy/sell advice.
- Added `gaon-conversational-reasoning-release-check` plus unit and Telegram integration coverage for context reuse, professional metric explanation, missing-context fallback, rerun boundary handling, and metadata suppression.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Hotfix 152.3 - Result Units and Presentation Integrity

- Added metric-semantics-aware conversational formatting so `expectancy`, average trade, average win/loss, ending equity, and initial capital are treated as capital-denominated amounts instead of percentages.
- Hid internal research identifiers and raw provenance keys such as strategy fingerprints, validation IDs, `quality_status=...`, and `source=...` from default user-facing Telegram responses.
- Replaced raw data-quality/source strings with Korean labels and deduplicated repeated warning prefixes.
- Added `gaon-result-presentation-release-check` plus unit and Telegram integration coverage for currency expectancy, zero-trade unavailable metrics, hidden fingerprints, and provenance-label rendering.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Hotfix 152.2 - Telegram Follow-up Persistence and Typo Tolerance

- Persisted Sprint 152 conversational MVP research context in existing versioned conversation session metadata so Telegram follow-ups survive runtime/Brain recreation across polling ticks.
- Split `last_research_context` from `last_response_context`; greeting, help, status, typo, and unknown messages no longer erase the prior research/comparison context.
- Added narrow deterministic typo tolerance for follow-up phrases such as `왜 그절? 판간했어?`, while keeping arbitrary research/tool/order routing fail-closed.
- Strengthened comparison wording for `trade_count=1` versus `trade_count=0` so Gaon does not claim stable superiority or fabricate confidence.
- Added `gaon-telegram-followup-release-check` plus unit and Telegram integration coverage for persisted context, typo follow-up, help/unknown preservation, chat-scoped metadata, and no unrelated tool calls.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Hotfix 152.1 - Conversational Follow-up Context Integrity

- Strengthened Sprint 152 follow-up handling so "why", "simple explanation", and "details" requests use the immediately previous research result from the same Telegram chat.
- Expanded `ConversationalMVPContext` with result kind, structured results, detail payload, source, fixture flag, quality status, and update timestamp.
- Added deterministic Korean missing-context fallback that does not call unrelated tools.
- Fixed comparison detail/simplification to preserve all compared symbols instead of rendering only the first payload.
- Added `gaon-conversation-context-release-check` plus Telegram integration coverage for chat isolation, context replacement, fixture warning conditions, and quality-status wording.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Sprint 152 - Gaon Conversational MVP

- Added deterministic Telegram-facing conversational intents for greeting, help, single-symbol analysis, symbol comparison, follow-up explanation, simplification, detail view, status query, and unknown fallback.
- Added Korean KRX symbol extraction for supported public symbols including `005930` Samsung Electronics and `000660` SK Hynix.
- Added human-readable deterministic research summaries that show total return, MDD, trade count, data period, quality status, reliability warnings, and next actions while hiding internal IDs and raw structured fields by default.
- Added fail-closed two-symbol comparison behavior: if any requested symbol fails, Gaon does not infer a ranking from partial success.
- Added session-scoped immediate follow-up context for Telegram chats without cross-chat leakage.
- Added `gaon-conversation-release-check` and Telegram regression coverage.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Sprint 151 - Dynamic KRX Universe Selection

- Added immutable `KRXUniverseRequest`, `KRXUniverseEntry`, `KRXUniverseExclusion`, `KRXUniversePolicy`, and `KRXUniverseResult` contracts.
- Added deterministic KRX universe selection by `trading_value` with canonical six-digit symbol tie-breaks.
- Added read-only `krx_universe_select` safe tool and CLI commands `krx-universe-select` and `krx-universe-release-check`.
- Connected explicit universe results into the existing multi-symbol research orchestrator while preserving explicit user-provided symbols as the highest priority.
- Kept provider universe selection fail-closed: unsupported markets, invalid dates, non-trading dates, provider failures, empty universes, zero-volume rows, and zero-trading-value rows are not silently accepted.
- Preserved schema v36, fixture/real provenance, no trading, no Champion auto-promotion, no approval bypass, and no strategy configuration mutation.

## Hotfix 150.5 - Production Multi-Symbol Yahoo Registry Alignment

- Closeout: marked Hotfix 150.5 COMPLETE after production merge `5f6ad1d` and implementation commit `519692c` were verified on VPS.
- Documented the production deployment root cause: the service was importing a stale copied `gaon` package from `.venv/lib/python3.12/site-packages` instead of `/opt/strategylab-v2/src/gaon`.
- Added `deployment-import-path-check` so deployments fail fast when Gaon is imported from outside the intended source tree.
- Updated VPS deployment and incident runbooks to require `git pull origin main`, `.venv/bin/pip install -e .`, import-path verification, and `systemctl restart strategylab-gaon`.
- Fixed the Hotfix 150.4 test gap where production-equivalent inspection did not verify the common zero-volume anomaly set plus each symbol's additional production evidence.
- Added symbol canonicalization for Yahoo anomaly lookups so `000660`, `000660.KS`, and equivalent KQ-prefixed forms resolve to the same registry key.
- Updated Yahoo zero-volume anomaly dates for `000660`, `005380`, `035420`, and `051910` to include the common 2022 provider anomaly set plus VPS-confirmed symbol-specific additions.
- Preserved KRX calendar boundaries: provider gaps remain provider anomalies, not exchange holidays.
- Kept unregistered zero-volume bars, unknown missing trading days, malformed OHLCV, and duplicate bars fail-closed.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and no configuration mutation.

## Hotfix 150.4 - Yahoo Multi-Symbol Data Quality

- Extended `real:yahoo-chart` anomaly classification for the Sprint 141-150 multi-symbol research universe: `005930`, `000660`, `005380`, `035420`, and `051910`.
- Kept `2022-01-03`, `2022-05-09`, and symbol-specific 2023 missing bars as provider gaps instead of KRX calendar holidays.
- Registered verified 2022 Yahoo zero-volume anomaly bars for the five-symbol research universe while keeping unregistered zero-volume bars blocking.
- Strengthened `historical-krx-data-quality-release-check` to validate all five research symbols and preserve symbol-specific anomaly isolation.
- Preserved schema v36, strict data quality gates, no trading, no Champion auto-promotion, no approval bypass, and no configuration mutation.

## Hotfix 150.3 - Multi-Symbol History Intent Collision

- Fixed a semantic collision where execution phrases such as `결과를 기록해줘` were misclassified as `multi_symbol_research_history`.
- Split multi-symbol routing into explicit execution, explicit status query, and explicit history query contracts.
- Added `multi_symbol_research` as a parsed conversation intent for explicit multi-symbol execution requests.
- Strengthened `telegram-routing-debug` and `telegram-multi-symbol-research-release-check` with `execution_intent`, `history_intent`, and `status_intent` diagnostics.
- Updated the production multi-symbol regression fixture to the full long Telegram request containing `기록해줘`.
- Preserved schema v36, read-only safe-tool execution, no trading, no Champion auto-promotion, no approval bypass, and no config mutation.

## Hotfix 150.2 - Production Multi-Symbol Routing Diagnostics

- Fixed production Telegram multi-symbol research requests that included explicit safety-boundary language being misclassified as unsafe and falling back to the generic stock-analysis persona.
- Added read-only `telegram-routing-debug` CLI diagnostics with normalized text metadata, intent, symbol/date extraction, route/tool selection, provider allowance, and fallback reason.
- Preserved priority order: `multi_symbol_research` before autonomous retest, single-symbol real research, and generic stock-analysis fallback.
- Added Telegram route selection logging without message body, secrets, or raw prompt content.
- Strengthened `telegram-multi-symbol-research-release-check` output with production-language, symbol/date, route/tool, persistence, provider-call, and generic-fallback fields.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and deterministic grounded reporting.

## Hotfix 150.1 - Telegram Multi-Symbol Routing

- Fixed production Telegram multi-symbol requests with explicit KRX symbol lists routing to generic stock-analysis fallback.
- Prioritized `multi_symbol_research` for explicit multi-symbol research evidence before retest and single-symbol real-research routes.
- Added deterministic extraction of KRX symbols and date ranges from the Telegram request text.
- Strengthened `telegram-multi-symbol-research-release-check` with the production Korean request, symbol extraction, period extraction, authoritative route, persistence, and provider-free execution checks.
- Preserved schema v36, no trading, no Champion auto-promotion, no approval bypass, and deterministic grounded reporting.

## Sprint 141-150 - Multi-Symbol Autonomous Research

- Added multi-symbol KRX research contracts, explicit/curated universe provenance, per-symbol evidence, cross-symbol aggregation, concentration analysis, sample sufficiency, and candidate generalization.
- Added schema v36 tables for multi-symbol runs, symbol evidence, candidate evidence, and universe snapshots.
- Added read-only safe tools `multi_symbol_research`, `multi_symbol_research_status`, and `multi_symbol_research_history`.
- Added CLI commands `multi-symbol-research-demo`, `multi-symbol-research-release-check`, `telegram-multi-symbol-research-release-check`, `multi-symbol-research-status`, and `multi-symbol-research-history`.
- Preserved Hotfix 130.1 style release-check/demo isolation and all no-trading/no-auto-promotion/no-approval-bypass boundaries.

## Hotfix 140.7 - Yahoo KRX Zero Volume Anomaly Classification

- Registered 11 Samsung Electronics (`005930`) Yahoo zero-volume anomalies from production 5-year inspection.
- Excluded registered zero-volume anomaly bars from backtest input and reported them as `provider_zero_volume_anomaly`.
- Kept unregistered zero-volume bars blocking and fail-closed.
- Extended `historical-krx-data-quality-release-check` output with `provider_zero_volume_anomaly_dates`.
- Preserved schema v35, strict OHLC validation, no trading, no Champion auto-promotion, and no approval bypass.

## Hotfix 140.6 - Historical KRX Data Quality Classification

- Added `2023-05-29` as a KRX closure while keeping `2022-01-03`, `2022-05-09`, and `2025-09-19` as exchange-open dates.
- Added Yahoo `005930` symbol-specific provider-gap classification for `2022-01-03` and `2022-05-09`.
- Added provider-specific zero-volume classification plumbing while keeping unregistered zero-volume bars blocking.
- Added `historical-krx-data-quality-release-check` and `historical-krx-data-quality-inspect`.
- Preserved schema v35, strict OHLC validation, no trading, no Champion auto-promotion, and no approval bypass.

## Hotfix 140.3 - Historical KRX Trading Calendar Accuracy

- Expanded `KRXTradingCalendar` historical closure coverage for 2021-2026 with annual market-closure overrides.
- Added 2023/2024 historical KRX closures for public holidays, election day, Labor Day, temporary holidays, and year-end exchange closures.
- Kept `2025-09-19` as an exchange-open date and preserved its `real:yahoo-chart` provider-gap classification.
- Added `historical-krx-calendar-release-check`, verifying 3-year Samsung-like Yahoo data leaves only `2025-09-19` as a non-blocking provider gap.
- Preserved schema v35, no trading, no automatic Champion promotion, no approval bypass, and release/demo isolation.

## Hotfix 140.2 - Telegram Retest Persistence Visibility

- Fixed retest history/status hiding production `autonomous-retest:*` runs because the artifact filter matched the broad `test:` substring inside `retest`.
- Narrowed retest artifact filtering to explicit release-check/demo/test prefixes only.
- Added richer persisted retest lineage in status/history payloads, including symbol, strategy/assumptions fingerprints, period counts, provider gaps, blocking findings, quality finding details, metrics, confidence, and warnings.
- Added `telegram-retest-persistence-release-check` to verify the Telegram authoritative retest route persists run/evidence state in an isolated DB and remains duplicate-message idempotent.
- Preserved release-check/demo isolation, no trading, no automatic Champion promotion, no approval bypass, and schema v35.

## Hotfix 140.1 - Telegram Autonomous Retest Routing

- Added explicit autonomous retest natural-language routing for Korean and English requests such as `재검증`, `표본이 부족하면`, `기간을 확장`, `18개월`, `3년`, `5년`, `retest`, and `expand period`.
- Routed explicit retest execution requests to the read-only authoritative `research_retest` tool before the older `krx_real_research` route.
- Added deterministic Telegram coverage proving provider calls are skipped, `research_retest` is audited, `krx_real_research` is not called, and retest lineage / stop reason are included in the final response.
- Preserved strict grounding, no trading, no automatic Champion promotion, no approval bypass, and no Telegram config mutation.

## Sprint 131-140 - Autonomous Retest Pipeline

- Added Retest Trigger Engine for insufficient sample and needs-retest decisions.
- Added deterministic adaptive period expansion from 6 months to 18 months, 3 years, and 5 years.
- Added real-market re-fetch / re-backtest orchestration that preserves strategy and execution-assumptions fingerprints.
- Added multi-period retest evidence lineage, stop policy, candidate re-evaluation, and advisory recommendation refresh.
- Added schema v35 tables: `research_retest_runs`, `research_retest_evidence`, and `research_period_plans`.
- Added read-only safe tools `research_retest_status` and `research_retest_history`.
- Added CLI commands `research-retest-demo`, `autonomous-retest-release-check`, `research-retest-status`, and `research-retest-history`.
- Preserved safety boundaries: no live trading, no KIS orders, no broker orders, no automatic Champion promotion, no approval bypass, no Telegram config mutation, no arbitrary shell/SQL, and no private repository dependency.

## Hotfix 130.1 - Research Operations State Isolation

- Isolated `research-ops-release-check` fixture writes from the target production SQLite database.
- Made `research-ops-demo` isolated by default and added an explicit `--persist` diagnostic mode.
- Hid release-check/demo/test artifacts from `research_operation_status` and normal `research-ops-report` output.
- Added `research-ops-cleanup --dry-run|--apply` to identify and remove existing release-check/demo/test artifacts while preserving real user research state.
- Preserved schema v34 and all no-trading/no-auto-promotion/no-approval-bypass boundaries.

## Sprint 121-130 - Research Operations

- Added research quality gate, statistical confidence scoring, candidate dominance analysis, period-expansion policy, and approval-gated strategy configuration changes.
- Added schema v34 tables for research operation reports, research config approvals, strategy config versions, and strategy config audit history.
- Added rollback-capable approved strategy configuration workflow.
- Added read-only safe tool `research_operation_status`.
- Added CLI commands `research-ops-demo`, `research-ops-release-check`, `research-config-approve`, `research-config-rollback`, and `research-ops-report`.
- Preserved safety boundaries: no live trading, no KIS orders, no broker orders, no automatic Champion promotion, no approval bypass, no arbitrary shell/SQL, and no private repository dependency.

## Hotfix 120.7 Structural Authoritative Grounding Validator

- Replaced metric literal blacklist handling with canonical metric alias parsing and structured evidence comparison.
- Removed broad `str(output)` numeric allowlisting from strict real-research grounding.
- Added `structural-authoritative-grounding-release-check`.
- Preserved fail-closed blocking for fabricated trade counts, wins/losses, MDD, returns, unsupported PF, RSI, MA, volume multiplier, stop, and take-profit claims.
- Preserved schema v33.

## Hotfix 120.6 Authoritative Backtest Metric Grounding

- Added structured authoritative metric evidence extraction for strict real-research reports.
- Added semantic aliases for wins/losses/trades/MDD/profit factor/returns without allowing arbitrary values.
- Added `authoritative-renderer-grounding-release-check`.
- Made `telegram-strict-real-research-release-check` repeatable on persistent DBs by checking audit append behavior.
- Preserved schema v33 and strict blocking for fabricated RSI, MA, volume multiplier, take-profit, mismatched trade count, and mismatched MDD claims.

## Hotfix 120.2 Real Provider Gap Classification

- Added provider-gap classification for Yahoo KRX daily data anomalies without changing the KRX exchange calendar.
- Classified `2025-09-19` as a `real:yahoo-chart` provider gap, not a KRX holiday.
- Added release-check warning allowlist behavior: provider-gap-only datasets can pass real-data checks while unknown missing trading days, malformed OHLCV, and duplicates remain blocking.
- Added `provider-gap-release-check` and Korean research-report disclosure for provider gaps.

## Hotfix 120.1 KRX Trading Calendar Quality

- Added deterministic `KRXTradingCalendar` support for daily KRX data-quality checks.
- Changed KRX daily missing-date validation to use trading dates instead of raw calendar dates.
- Added `krx-trading-calendar-release-check`.
- Preserved schema v33 and existing malformed OHLCV, duplicate bar, stale data, and real missing trading-day findings.

## Real KRX Data Activation

- Added `YahooKRXHistoricalDataProvider` for free public KRX-listed daily OHLCV history.
- Added explicit env gates: `GAON_REAL_MARKET_DATA_ENABLED`, `GAON_MARKET_DATA_PROVIDER`, and `GAON_MARKET_DATA_TIMEOUT_SECONDS`.
- Added production-only `real-krx-data-release-check`.
- Updated `krx_real_research` safe tool and `krx-real-research-demo` to use the configured provider while preserving fixture default behavior for CI.
- Preserved fail-closed behavior: provider failure returns `real_data_unavailable` and does not fall back to fixture.

## Sprint 111-120 - KRX Real Research Pipeline

- Added KRX public-data provider boundary and explicit fixture/real source separation.
- Added reproducible KRX dataset builder/cache and schema v33 `krx_real_research_memories`.
- Added Korean user-strategy parser with per-field provenance.
- Added deterministic rule-based backtest engine with cost assumptions and look-ahead prevention.
- Added real performance metrics, walk-forward validation, evidence-based critic, improvement candidates, comparison, and Korean research reports.
- Added read-only safe tool `krx_real_research`.
- Added CLI commands `strategy-parser-release-check`, `real-backtest-release-check`, `krx-real-research-demo`, and `krx-real-research-release-check`.

## Hotfix 110.2 Korean Response Language Consistency

- Added Korean final-response normalization for Korean Telegram/user messages.
- Removed `<output>` and `<response>` wrapper tags before final response persistence.
- Translated internal research critic findings and improvement suggestions into Korean user-facing text.
- Added deterministic Korean missing-data UX for quality-score requests.
- Added repeatable `korean-response-release-check`.

## Hotfix 110.1 Research Grounding Context Isolation

- Isolated user-provided strategy conditions from fixture/default strategy metadata in research critique responses.
- Sanitized provider tool-result payloads so fixture candidate parameters, metrics, and regime metadata are not exposed as current user strategy values.
- Added Korean deterministic missing-data UX for quality-score requests without stored actual backtest quality results.
- Added repeatable `research-context-isolation-release-check`.

## Hotfix Research Grounding and Telegram Routing

- Grounded research responses in user input, safe-tool output, persisted memory, fixtures, external backtest payloads, and dataset metadata.
- Added deterministic routing for strategy critique/improvement, research memory search, strategy quality score, data quality, and backtest requests.
- Ensured empty research memory reports no stored match instead of access or permission failure.
- Added fixture disclosure and provenance-preserving formatting for research safe-tool responses.
- Added repeatable `research-grounding-release-check`.

## Sprint 56-60 - Gaon LLM Agent

- Added generic OpenAI-compatible provider diagnostics and tool-call support.
- Added native provider-requested safe read-only tool execution.
- Added multi-turn follow-up handling with bounded tool-result memory.
- Added safe conversational agent planner with approval-boundary stops.
- Added LLM agent release hardening, CLI diagnostics, prompt-injection tests, and low-resource VPS limits.

## Sprint 51-55 - Gaon LLM Brain

- Added persistent LLM conversation sessions and messages.
- Added bounded contextual memory orchestration from read-only runtime state.
- Added safe read-only tool registry, execution policy, and audit storage.
- Added Telegram conversational agent routing while preserving offset and duplicate protection.
- Added assistant/conversation/tool CLI inspection commands and release checks.

## Sprint 47 Strategy Execution Runtime

- Added Strategy Execution Runtime with `strategy_execution_policy_v1`.
- Added explicit `DISABLED`, `PAPER`, and `LIVE` modes with default `DISABLED`.
- Added active-Champion binding and stale Champion execution blocking.
- Added PAPER execution orchestration using the existing paper adapter stack.
- Added LIVE planning gates against paper revalidation, while keeping live execution blocked because the broker adapter is unavailable.
- Added runtime schema v18 with strategy execution plan and run tables.
- Added CLI commands for policy, status, plan, run, show, and history.
- Preserved safety boundaries: no live KIS, no broker credentials, no real orders, no automatic approval, no automatic rollback, and no MyMoneyGuard dependency.

## Sprint 46 Paper Revalidation and Kill/Rollback Gates

- Added deterministic Paper Revalidation Engine with `paper_revalidation_policy_v1`.
- Added `LIVE_ELIGIBLE`, `HOLD`, `KILL`, `ROLLBACK_RECOMMENDED`, and `REVIEW` safety decisions.
- Added runtime schema v17 with paper revalidation request and report tables.
- Added CLI commands for policy display, revalidation, report show, and history.
- Added events and metrics for live eligibility, hold, kill, rollback recommendation, and review outcomes.
- Preserved safety boundaries: no live KIS, no broker credentials, no real orders, no automatic rollback, no automatic approval, and no registry mutation.

## Sprint 45 Paper Trading Forward Test

- Added paper-only Champion forward-test sessions.
- Reused existing `PaperTradingAdapter`, `TradingExecutionService`, `TradingRiskPolicy`, and `SQLiteTradingRepository`.
- Added session lifecycle commands for create, start, pause, resume, complete, cancel, show, list, simulated order, and summary.
- Added runtime schema v16 with paper trading session, observation, and summary tables.
- Added events and metrics for paper session lifecycle and simulated orders.
- Added unit and integration coverage for active-Champion-only creation, stale Champion rejection, lifecycle transitions, summary generation, persistence, CLI smoke, and v15-to-v16 migration.
- Preserved safety boundaries: no live KIS, no broker credentials, no real orders, no paper-to-live promotion, no automatic trading, and no MyMoneyGuard dependency.

## Sprint 44 Champion Registry and Approval Promotion

- Added approval-gated Champion Registry for the stable `default` slot.
- Added explicit bootstrap, promotion request, approve, reject, history, registry show, and rollback CLI commands.
- Added runtime schema v15 with Champion registry, version history, promotion request, and promotion decision tables.
- Added events and metrics for bootstrap, promotion request, approval, rejection, activation, and rollback.
- Added unit and integration coverage for idempotent promotion requests, approval, rejection, rollback, persistence, and migration.
- Preserved safety boundaries: no direct `PROMOTION_CANDIDATE` activation, no live KIS, no broker orders, no automatic trading, no automatic approval, and no MyMoneyGuard dependency.

## Sprint 43 Champion / Challenger Evaluation Engine

- Added deterministic Champion / Challenger Evaluation Engine.
- Added `StrategyRole`, `ChampionChallengerDecision`, request, policy, comparison, report, repository, event, and metric contracts.
- Added `champion_challenger_policy_v1` with validation, fingerprint, return improvement, MDD degradation, profit factor, sample period, and trade count comparisons.
- Added runtime schema v14 with Champion / Challenger evaluation request and report tables.
- Added CLI commands for policy display, evaluation, report show, and history.
- Documented that `PROMOTION_CANDIDATE` is not `PROMOTED` and cannot trigger trading or active strategy switching.

## Sprint 42 Strategy Validation Engine

- Added deterministic Strategy Validation Engine for normalized Sprint 41 `BacktestResult` records.
- Added `ValidationRequest`, `ValidationPolicy`, `ValidationRule`, `ValidationRuleResult`, `ValidationReport`, status, severity, and evidence contracts.
- Added conservative `validation_policy_v1` with MDD, trade count, sample period, profit factor, fingerprint, multi-run, and overfitting heuristic checks.
- Added runtime schema v13 with `validation_requests` and `validation_reports`.
- Added validation lifecycle events, runtime metrics, Research Agent validation routing, Executive Planner validation capability, and CLI commands.
- Documented that Validation PASS does not automatically promote, deploy, trade, approve, or switch strategies.

## Hotfix Telegram Runtime Worker and systemd Service

- Wired persistent Telegram polling into `GaonRuntimeService` through a bounded runtime worker.
- Updated CLI `run` so default execution is a persistent service loop and `run --once` performs exactly one tick.
- Reused the existing `telegram-poll-once` logic, SQLite Telegram state repository, offset persistence, processed message duplicate guard, and execute/dry-run gates.
- Isolated transient Telegram failures so the runtime can continue on later ticks, with durable runtime events and metrics.
- Updated systemd service execution from one-shot `health` to persistent `run --db /var/lib/strategylab/gaon-runtime.sqlite`.

## Hotfix Telegram Poll Offset Persistence

- Connected `telegram-poll-once` execute path to the existing SQLite Telegram state repository.
- Added saved offset loading when `--offset` is omitted and documented explicit `--offset` precedence.
- Added processed message duplicate protection so repeated poll executions do not send duplicate replies.
- Persisted highest safe `next_offset` for sent, duplicate, unauthorized, and ignored updates.
- Added unit and integration coverage for offset persistence, duplicate skipping, restart preservation, explicit offsets, and unauthorized/ignored update progression.

## Sprint 41 v1 Backtest Adapter Foundation

- Added runtime schema v12 for backtest requests and normalized backtest results.
- Added BacktestRequest, BacktestStrategyRef, BacktestDatasetRef, BacktestPeriod, BacktestExecutionContext, BacktestResult, BacktestMetrics, BacktestTradeSummary, and BacktestStatus contracts.
- Added BacktestAdapter, FakeBacktestAdapter, LocalProcessBacktestAdapter, SQLiteBacktestRepository, and BacktestExecutionService.
- Added v1 result normalization, optional metric preservation, stable reproducibility fingerprints, bounded local-process invocation handling, lifecycle events, runtime metrics, CLI commands, and v11-to-v12 migration coverage.
- Exposed the adapter through the existing Executive Planner and Research Agent in a bounded fake-adapter path.
- The real v1 backtest engine is not required for automated tests.
- Did not add Champion/Challenger ranking, strategy promotion, active strategy switching, paper trading promotion, live strategy deployment, KIS integration, MyMoneyGuard integration, automatic trading, automatic approval, arbitrary shell execution, network calls, or private repository dependencies.

## Sprint 40 Trading Adapter Foundation

- Added runtime schema v11 for trading requests and structured simulation results.
- Added structured trading models for intents, actions, sides, order types, requests, decisions, execution context, results, statuses, account snapshots, and position snapshots.
- Added TradingRiskPolicy, TradingExecutionService, SQLiteTradingRepository, and deterministic PaperTradingAdapter.
- Extended Executive Planner and Agent Dispatcher with a safe trading simulation route.
- Added durable trading lifecycle events, runtime metrics, deterministic trading CLI commands, unit tests, integration tests, and v10-to-v11 migration coverage.
- Live trading is not implemented.
- Did not add KIS REST, KIS WebSocket, broker authentication, real account access, real order execution, automatic trading, automatic approval, MyMoneyGuard integration, live market data, Telegram trading commands, paid-provider fallback, or unrestricted shell execution.

## Sprint 39 Daily Research Pipeline

- Added runtime schema v10 for daily research profiles and runs.
- Added DailyResearchTopic, DailyResearchProfile, DailyResearchRun, DailyResearchRunStatus, and DailyResearchResult contracts.
- Added DailyResearchRepository with duplicate profile rejection, deterministic listing, enable/disable workflow, durable run storage, and duplicate run protection.
- Added DailyResearchPipeline on top of the Sprint 38 ScheduledJobRepository; no second scheduler was introduced.
- Added deterministic daily research execution through ResearchRequest, deterministic planner, bounded fake evidence search, context builder, markdown/json report generation, and pending-review knowledge proposal persistence.
- Added durable events, runtime metrics, CLI commands, unit tests, integration tests, and v9-to-v10 migration coverage.
- Did not add Telegram delivery, email, Notion sync, GitHub polling, live market data, Trading Adapter execution, broker/KIS/MyMoneyGuard access, external AI calls, vector DB, automatic approval, shell execution, or plugin execution.

## Sprint 38 Scheduler Automation

- Added runtime schema v9 for durable scheduled automation jobs and runs.
- Added ScheduleDefinition, ScheduledJob, ScheduledRun, ScheduledRunStatus, and ScheduledExecutionRequest contracts.
- Added ScheduledJobRepository with explicit creation, enable/disable, lookup, deterministic listing, due lookup, bounded attempts, and duplicate run protection.
- Added ScheduledAutomationRunner that routes due jobs through Executive Planner and Agent Dispatcher without bypassing approval or capability boundaries.
- Added scheduled lifecycle durable events, runtime metrics, and schedule CLI smoke commands.
- Did not add Daily Research business logic, Telegram delivery, live Trading/KIS execution, automatic approval, paid-provider fallback, or private repository dependencies.

## Sprint 37 Multi-Agent Execution Framework

- Added Agent, AgentRequest, AgentExecutionContext, AgentResult, AgentCapability, and AgentStatus contracts.
- Added explicit AgentRegistry with duplicate registration rejection, unknown-agent rejection, stable lookup, capability inspection, and deterministic ordering.
- Added AgentDispatcher that consumes ExecutivePlan, validates capabilities, invokes one agent safely, isolates failures, and blocks approval-required plans.
- Added deterministic ResearchAgent, CodingAgent, MemoryAgent, and non-executing TradingAgentPlaceholder.
- Added agent lifecycle durable events, runtime metrics, and `agent-run` CLI smoke path.
- Did not add scheduler execution, daily research automation, Telegram-triggered execution, broker/KIS execution, automatic approval, arbitrary shell execution, or dynamic plugin loading.

## Sprint 36 Executive Planner

- Added immutable ExecutiveRequest, ExecutivePlan, RoutingDecision, AgentSelection, ToolSelection, and ExecutivePlanner contracts.
- Added deterministic routing for research, memory, runtime status, human review, and unsupported requests.
- Added provider-backed planning through the existing Assistant Provider Registry with free-only and paid-provider guardrails.
- Added approval-required flag propagation for execution-capable or policy-changing requests.
- Added ExecutivePlanCreated durable event helper, runtime metrics integration, and CLI plan inspection.
- Did not add multi-agent execution, scheduler execution, trading adapter execution, or Telegram integration.

## Sprint 35 Research Brain Orchestration

- Added schema v8 Research Brain run and checkpoint tables.
- Added deterministic ResearchOrchestratorV3 with run states, checkpoints, reports, resume, and metrics.
- Added research CLI smoke commands for plan, run, status, report, and resume paths.
- Added free-only runtime configuration defaults and paid-provider guardrails.
- Added Phase B Research Brain architecture, runtime operations, free-only mode, and release candidate documentation.

## Sprint 30 Validated Research Planning

- Added bounded ResearchRequest, ResearchPlan, and ResearchStep contracts.
- Added deterministic planner with stable plan hash and plan lifecycle event support.
- Added allowlisted research step types, dependency validation, cycle rejection, and step limit enforcement.
- Added optional provider-backed planner with free-only enforcement and structured output validation.
- Added planner metrics coverage.

## Sprint 31 Safe Evidence Search Providers

- Added provider-neutral search contracts with normalized source metadata.
- Added fake, local fixture, RSS/Atom, and optional disabled-by-default web search providers.
- Added canonical URL normalization, domain allow/deny filtering, result limits, content-size limits, duplicate URL removal, timeout and bounded retry behavior.
- Added search metrics and durable event helper coverage without live network tests.

## Sprint 32 Evidence Ranking and Context Building

- Added EvidenceItem, EvidenceBundle, citation, and evidence-to-context contracts.
- Added canonical URL normalization reuse, content hashing, exact duplicate removal, conservative near-duplicate detection, stable ranking, and citation ID assignment.
- Added memory/external evidence merge, context budget enforcement, truncation diagnostics, and contradiction preservation.
- Added explicit source-quality rule hook with conservative defaults.

## Sprint 33 Evidence-Backed Knowledge Proposals

- Added schema v6 knowledge proposal and trusted knowledge tables.
- Added evidence-linked research knowledge claims, proposal confidence, stable proposal hashes, explicit versions, provenance, review/expiration metadata, and insufficient-evidence status.
- Added contradiction surfacing and proposal lifecycle event/metrics helpers.
- Kept proposal persistence separate from trusted knowledge and disallowed direct trusted promotion.

## Sprint 34 Auditable Research Approval Workflow

- Added schema v7 research approval decision table and idempotency index.
- Added proposal hash/version-bound approval requests and approve/reject/revise decision contracts.
- Added stale proposal rejection, repeated decision idempotency, promotion replay protection, audit events, and approval/rejection metrics.
- Added dry-run research proposal CLI smoke commands.

## Sprint 24 Provider Registry and Routing

- Added explicit assistant provider registry with stable-name lookup, duplicate registration protection, and unknown provider fail-fast behavior.
- Added configuration-based deterministic and OpenAI-compatible provider selection.
- Added health-based deterministic fallback with structured fallback reason.
- Added routing tests with fake OpenAI-compatible transport only; no real provider network calls are required.

## Sprint 25 Explicit Plugin Lifecycle

- Added explicit plugin metadata, capability, health, registry, and manager contracts.
- Added allowlist-only lifecycle for configure, start, health, and reverse-order stop.
- Added duplicate plugin ID rejection, disabled-plugin guard, failure isolation, and redacted failure records.
- Added fake Telegram, Notion, and Trading plugin tests without live network calls.

## Sprint 26 Runtime Metrics and Observability

- Added standard-library internal metrics collector for counters, gauges, and timing observations.
- Added immutable metrics snapshot/export model and CLI `metrics` output.
- Added bounded component and label validation to prevent prompt, message, chat ID, token, API key, secret, or arbitrary payload leakage.
- Added concurrency and CLI tests without external observability dependencies.

## Sprint 27 Durable Event Store and Safe Replay

- Added schema v4 durable append-only event store and replay checkpoint tables.
- Added deterministic event append/read, duplicate protection, bounded replay batches, oversized payload rejection, and v3-to-v4 migration coverage.
- Added dry-run replay with side effects suppressed by default and checkpoint advancement only during non-dry-run successful projection processing.
- Added projection failure isolation and replay failure recording.

## Sprint 28 Long-Term Memory Foundation

- Added schema v5 long-term memory table and deterministic SQLite repository.
- Added `MemoryNamespace`, `MemoryLifecycle`, `MemoryRecord`, retention policy, conflict flags, and revalidation flags.
- Enforced proposal-first writes, trusted-workflow validation, system namespace authorization, and secret marker rejection.
- Added deterministic read-only context retrieval and backup/restore coverage without vector DB or automatic LLM validation.

## Sprint 29 Phase A Integration and v2.1 RC

- Integrated metrics and explicit plugin lifecycle into the controlled runtime service.
- Added event replay dry-run CLI diagnostic.
- Added Gaon Phase A architecture document, provider/plugin/event/memory ADRs, and project vision document.
- Updated README, release notes, operations guidance, and test results for v2.1 Release Candidate status.

## Sprint 23 v2 Release Candidate and Trading Adapter Contract

- Added broker-free `gaon.adapters.TradingAdapter` protocol and fake adapter contract tests.
- Added read-only account, position, market, and runtime status contracts.
- Added order command lifecycle, risk gate contracts, execution-disabled default, and approval reference requirement.
- Added v1 integration rollout plan: read-only -> paper -> shadow -> approval-gated execution.
- Documented that no live broker, KIS API, MyMoneyGuard private code, or Telegram-triggered order execution is connected.

## Sprint 22 Security, Chaos, and Resilience Coverage

- Replaced SQLite file-copy backup with `sqlite3.Connection.backup()` and atomic destination replacement.
- Added deterministic tests for prompt-injection-as-data, provider failure, duplicate storm, restart recovery, duplicate scheduler tick, log redaction, bounded retry, and backup restore.

## Sprint 21 Production Runtime Loop

- Added controlled `GaonRuntimeService` loop with readiness, recovery, stop event, bounded drain, tick injection, and structured redacted logs.
- Added CLI commands for `run`, `status`, and `backup`.

## Sprint 20 Durable Queue, Scheduler, and Recovery

- Added schema v3 runtime queue with PENDING, LEASED, RUNNING, SUCCEEDED, FAILED, and CANCELLED states.
- Added lease timeout recovery, durable scheduler idempotency, and DB-backed duplicate message guard.

## Sprint 19 SQLite Repository Layer

- Added runtime repository protocols and SQLite implementations for Telegram state, audit events, approvals, proposals, runs, scheduler jobs, and notification attempts.
- Added schema v2 migration and centralized runtime JSON serialization validation.

## Sprint 18 Approval Security Hardening

- Added explicit approval states and HMAC-SHA256 token digest storage.
- Added single-use approval consumption bound to actor, chat, proposal, approval, expiry, nonce, and run ID.
- Added execute-mode approval signing secret validation.

## Sprint 14 Memory-Aware Conversation

- Added read-only conversation context contracts for retrieved memory, research context, references, and build results.
- Added deterministic Learning Memory context builder with STRICT/BROAD/GLOBAL fallback.
- Added duplicate record removal, warning propagation, conflict and revalidation state summaries, and confidence-as-ranking-signal messaging.
- Connected memory context to selected research and memory intents without mutating repositories.
- Added Telegram memory query end-to-end coverage with fake runtime flow.

## Sprint 15 Guarded Assistant Provider Integration

- Expanded Assistant Provider contracts with capabilities, health, metadata, and provider error classes.
- Added deterministic fallback provider and OpenAI-compatible HTTP provider with injectable transport.
- Added prompt builder that separates instructions from user text and retrieved memory data.
- Added provider response validation, secret masking, timeout/malformed response fallback, and safety bypass for order/approval requests.
- Added fake Telegram/provider end-to-end coverage without real network calls.

## Sprint 16 Guarded Research Assistant Orchestration

- Added deterministic research request planner, proposal, approval, run, review, and queue contracts.
- Added explicit approval validation with actor, chat, token, and expiry checks.
- Added run state machine with terminal states and approval-gated running transition.
- Added in-memory deterministic queue with deduplication and retry limits.
- Added research orchestration unit and integration flow tests without autonomous execution.

## Sprint 17 Production Runtime Service

- Added SQLite runtime state schema, migrations, offset recovery, processed message idempotency, audit event storage, and backup helper.
- Added health/readiness/db-check CLI paths without secret output.
- Added service and worker foundations with readiness gate, duplicate guard, and bounded retry policy.
- Added systemd service example, env example, install/upgrade/rollback guide scripts, and VPS operations documentation.
- Added restart recovery and runtime service smoke tests.

## Sprint 13 Conversational Assistant Foundation

- Added deterministic Korean natural-language intent routing for greetings, Gaon calls, help, status, market status, stock analysis, schedules, backtests, recent research, and memory search requests.
- Added Gaon persona responses that address the user as `영하님` and avoid claiming disconnected work was executed.
- Added `AssistantProvider` request/response contracts for future OpenAI or local LLM integrations without adding any network provider or SDK dependency.
- Updated Conversation Runtime to record the response route and preserve event bus publication and approval/order safety boundaries.
- Added Telegram ordinary text end-to-end tests through the existing safe production smoke path.
- Documented that market data, schedule, stock analysis, and backtest execution are future provider/adapter connections.

## Telegram Production Connection

- Added a standard-library Telegram Bot API client with injectable HTTP transport.
- Added `getMe`, `getUpdates`, `sendMessage`, `deleteWebhook`, and `getWebhookInfo` operations.
- Added safe error mapping for authentication, rate limit, server, malformed JSON, `ok=false`, timeout, and oversized response cases.
- Added production smoke CLI commands: `telegram-get-me`, `telegram-discover-chat`, `telegram-send-smoke`, and `telegram-poll-once`.
- Added fail-closed execution gates for runtime mode, dry-run, Telegram enablement, bot token, explicit `--execute`, and allowed chat IDs.
- Added private text update parsing, ignored update results, chat discovery deduplication, message preview limiting, and manual offset reporting.
- Added fake HTTP unit/integration tests; no real Telegram token or network call is required in automated tests.

## Gaon Runtime Collaboration

- Fixed Windows-safe runtime timezone validation for `UTC` and `Asia/Seoul`.
- Strengthened runtime config validation for mode, booleans, HH:MM times, weekdays, and execute-mode guards.
- Replaced ambiguous CLI `--dry-run` defaults with explicit mutually exclusive dry-run/execute flags.
- Hardened Learning Memory snapshots with `claims` export/import.
- Added STRICT/BROAD/GLOBAL related-memory modes, token overlap, aliases, and EvidenceType quality scoring.
- Added `gaon.runtime` configuration, events, in-memory event bus, conversation runtime, notifications, reports, scheduler, and safe dry-run CLI.
- Added Telegram dry-run contracts, update parsing, authorization, formatting, and conversation bridge.
- Added Notion dry-run contracts, mapping, idempotent sync, and report payloads.
- Added runtime collaboration docs, ADRs, RFC, operations guides, unit tests, and integration tests.

## Sprint 12-B Learning Memory Repository

- Added `LearningRepository` protocol and deterministic `InMemoryLearningRepository`.
- Added duplicate and conflict candidate detectors without automatic merge or resolution.
- Added chronological lookup, project/strategy/market AND filters, and defensive copy storage behavior.
- Added append-only audit event workflow with target queries.
- Strengthened KnowledgeApproval and PolicyApproval scope matching.
- Added ISO 8601 UTC timestamp validation for Learning Memory contracts.
- Added golden JSON and migration compatibility fixtures.
- Added Sprint 12-B repository tests and documentation updates.
- Added related-memory deterministic retrieval with score breakdown.
- Added repository JSON export/import and explicit v0 to v1 migration path.
- Added synthetic golden fixtures under `tests/fixtures/learning_memory/`.
- Added Research Brain to Learning Memory conversion and no-auto-save preparation workflow.
- Added `PreferenceApproval` as a separate approval contract.

## Sprint 12-A Learning Memory Contracts

- Accepted ADR-0004 and ADR-0005 for Sprint 12 implementation.
- Updated RFC-0003 to accepted for implementation.
- Added Sprint 12-A Learning Memory domain contracts.
- Reused existing `EvidenceRecord` instead of creating a duplicate evidence model.
- Added separate `KnowledgeApproval` and `PolicyApproval` contracts.
- Added approval gates, rollback gates, confidence limits, preference protection, and versioned JSON tests.

## Sprint 11 Development Start

- Added Gaon Development Contract v1.0.
- Added `gaon.learning` package boundary.
- Added Learning Memory, Evidence, Knowledge, Experience, Policy, and Confidence contracts.
- Added tests for evidence requirements, knowledge validation approval, policy rollback metadata, and forbidden autonomous actions.
- Added Sprint 11 Brief, ADR-0001, RFC-0001, Learning Memory guide, and Conversation Engine boundary.
- Updated roadmap terminology from Memory to Learning Memory for Sprint 12 planning.
- Added Research Brain contracts for Research Goal, Plan, Session, Interview, and Journal.
- Hardened Research Brain with explicit session transitions, terminal completed sessions, pending interview answers, and versioned JSON round-trip support.

## v2.0 Foundation Release Candidate

- Added Core foundation.
- Added Market Engine foundation.
- Added Strategy Framework foundation.
- Added Backtest v2 deterministic foundation.
- Added Portfolio Engine foundation.
- Added Risk Engine foundation.
- Added AI Research review contract.
- Added Dashboard view model foundation.
- Added Broker Connector and Paper Trading foundation.
- Added release verification script and documentation.
# Sprint 48

- Added deterministic approved Champion strategy handoff packages.
- Added handoff approval/rejection persistence and CLI inspection commands.
- Added v19 runtime schema tables for handoff packages and approvals.

# Sprint 49

- Added approval-gated strategy deployment workflow.
- Added fake and local-safe deployment adapters.
- Added v20 runtime schema tables for deployment requests, runs, and backups.

# Sprint 50

- Added Gaon v5.0 Release Candidate pipeline orchestration.
- Added v21 pipeline run/checkpoint persistence and resume-safe approval waits.
- Added v5 CLI inspection and release-check commands.
- Added release, recovery, and VPS upgrade documentation.

# Sprint 50 Hotfix

- Made `v5-demo --dry-run` repeatable on persistent SQLite runtime databases.
- Namespaced demo-created IDs by run id without weakening existing uniqueness constraints.

# Sprint 61-70

- Added fixture-backed external web research foundation with normalized citations, freshness, trust metadata, and SSRF protections.
- Added read-only structured data tools for weather, exchange rates, market data, news search, and web search.
- Extended bounded agent planning to select external read-only research tools.
- Added strategy research planning, challenger experiment creation, deterministic fixture backtest, validation, Champion comparison, and advisory report generation.
- Added v28 runtime schema tables for strategy research plans, experiments, and reports.
- Added `external-research-release-check` and `strategy-research-demo` CLI commands.

# Sprint 71-80

- Added AI Quant Researcher foundation with fixture-backed KRX market data, news scoring, theme strength, supply-demand analysis, candidate strategy generation, automated fixture backtests, performance comparison, strategy improvement, evolution, and research reports.
- Added read-only `krx_market_data` Safe Tool.
- Added v29 runtime schema table for quant research reports.
- Added `quant-research-release-check` and `quant-research-demo` CLI commands.

# Sprint 81-90

- Added AI Quant Scientist foundation with feature discovery, feature selection, walk-forward validation, Monte Carlo robustness scoring, market regime detection, meta-strategy selection, portfolio allocation, ensemble decisions, explanations, and scientist reports.
- Added read-only `feature_discovery` Safe Tool with source, trust, and freshness metadata.
- Added v30 runtime schema tables for AI Scientist reports, feature importance, walk-forward windows, and Monte Carlo results.
- Added `feature-discovery-demo`, `feature-discovery-release-check`, `ai-scientist-demo`, and `ai-scientist-release-check` CLI commands.
- Preserved research-only safety boundaries: no orders, no automatic Champion promotion, no approval bypass, and no private repository dependency.

# Hotfix 90.1

- Hardened long Telegram response delivery with `finish_reason=length` truncation detection and bounded provider continuation.
- Raised the default assistant output limit to `2048` tokens and added `GAON_ASSISTANT_MAX_CONTINUATIONS`.
- Replaced Telegram hard slicing with source-preserving chunking below the API limit and visible `[n/m]` ordering.
- Added bounded retry and safe error classification for transient Telegram send failures.
- Added `long-response-release-check` and long-response reliability tests.

# Hotfix 90.2

- Made `long-response-release-check` repeatable on persistent SQLite databases by namespacing each check with a unique run id.
- Preserved schema v30 and Hotfix 90.1 long-response behavior.

# Sprint 91-100

- Added Self-Improving Quant Researcher foundation with deterministic research critique, traceable improvement planning, bounded iteration, lineage tracking, research memory, knowledge relationships, novelty detection, quality scoring, tournaments, and autonomous research orchestration.
- Added v31 runtime schema tables for research memories, lineage, critiques, iterations, quality scores, concepts, and concept relationships.
- Added read-only safe tools: `research_memory_search`, `strategy_critique`, `strategy_quality_score`, `research_candidate_compare`, and `research_lineage`.
- Added `research-critic-demo`, `research-memory-demo`, `research-iteration-demo`, `research-tournament-demo`, `autonomous-research-demo`, and `self-improving-research-release-check`.
- Preserved safety boundaries: no source-code self-modification, no shell, no arbitrary SQL, no live order, no automatic Champion promotion, no approval bypass, and no private repository dependency.

# Sprint 101-110

- Added real-market/backtest integration contracts with market data domain models, provider interface, data quality engine, dataset registry/cache, StrategySpec, external backtest JSON request/result contracts, reproducibility comparison, and Real Research Gateway.
- Added v32 runtime schema tables for market datasets, strategy specs, backtest runs, real backtest results, and real research reports.
- Added read-only safe tools: `market_data_status`, `dataset_lookup`, `data_quality_check`, `backtest_strategy`, `backtest_result`, and `compare_backtests`.
- Added `market-data-demo`, `data-quality-demo`, `backtest-contract-demo`, `external-backtest-demo`, `real-research-demo`, and `real-research-integration-release-check`.
- Preserved public/private boundaries: no private repository dependency, no hard-coded private path, no arbitrary shell, no arbitrary SQL, no generated Python strategy execution, no live order, no automatic deployment, and no automatic Champion promotion.

# Hotfix 120.3

- Added strict real research grounding for Telegram/LLM-facing KRX backtest reports.
- Real research final responses now prefer deterministic Korean structured reports when provider text invents or conflicts with `BacktestResult` metrics.
- Added `strict-real-research-grounding-release-check`, idempotent run IDs, and regression tests for fabricated metric suppression.
- Preserved schema v33 and safety boundaries: no live trading, broker order, automatic Champion promotion, approval bypass, arbitrary shell/SQL, or generated Python execution.

# Hotfix 120.4

- Routed production Telegram real KRX research requests through authoritative `krx_real_research` before provider free-form generation.
- Added fail-closed strict real research metric validation for provider output and Telegram final responses.
- Added `telegram-strict-real-research-release-check` covering the production Korean request path end to end.
- Preserved schema v33 and safety boundaries: no live trading, broker orders, automatic Champion promotion, or approval bypass.

# Hotfix 120.5

- Added structured Telegram research failure classification for market data, data quality, backtest, tool, LLM timeout, and internal errors.
- Telegram research failures now log traceback server-side while returning Korean user-facing messages without Python exception text or fabricated research results.
- Authoritative real research tool failures remain fail-closed and do not fall back to provider free-form answers.
- Added `telegram-real-research-failure-routing-release-check`.

# Hotfix 140.7.1

- Added `tzdata` as a runtime dependency so `ZoneInfo("Asia/Seoul")` works consistently on Windows and Linux installations.
- Added a timezone dependency regression test for the Yahoo KRX debug path and other IANA timezone consumers.
- Preserved schema v35 and Hotfix 140.7 zero-volume anomaly fail-closed policy.
