# Research Grounding

Status: Hotfix 90+  
Scope: Telegram and LLM safe-tool research responses

## Objective

Gaon must not invent quantitative strategy results in conversational research replies. Research answers are grounded in one of these sources only:

- user input
- safe-tool output
- persisted research memory
- fixture payloads
- external backtest result payloads
- real market dataset metadata

## Response Contract

Research responses separate:

- Verified data: fields returned by safe tools or explicitly provided by the user.
- Qualitative analysis: critique findings and interpretation that do not add new measured results.
- Hypothesis or suggestion: next-step ideas that require validation before use.

Unavailable metrics are reported as unavailable. Fixture data is disclosed with `fixture_backed=true` and must not be described as real historical market performance.

## Context Isolation

User-provided strategy conditions are isolated from fixture/default strategy metadata. Fixture candidate fields such as default volume multipliers, default risk percentage, internal metrics, and regime tags must not be presented as values of the current user strategy.

Provider-backed tool synthesis receives sanitized research tool payloads. For `strategy_critique`, candidate parameters, candidate metrics, and fixture regime metadata are removed before the provider sees the tool result. The response may reference user-provided conditions only when they are present in the user message.

When a quality-score request has no actual stored backtest-based result for the current user strategy, Gaon returns a Korean deterministic missing-data response instead of using fixture quality scores as if they belonged to the user strategy.

## Routing

Deterministic routing prioritizes specific research intents before generic status routes:

- strategy weakness, risk, critique, improvement -> `strategy_critique`
- similar or past research memory -> `research_memory_search`
- strategy quality score -> `strategy_quality_score`
- backtest request -> `backtest_strategy`
- data quality request -> `data_quality_check`

Empty memory results do not block improvement requests. Empty memory means no stored match, not missing system access.

## Provider Boundary

Provider-backed synthesis receives the same grounding policy. If a provider tool-result response fabricates known fixture-only metrics, Gaon falls back to deterministic grounded formatting for the safe-tool result.

## Safety

This hotfix does not add live KIS, broker orders, automatic Champion promotion, arbitrary shell, arbitrary SQL, secret access, private repository dependency, DB schema changes, or migrations.
