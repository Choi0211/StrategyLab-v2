# ADR-0001: Learning Memory as Gaon Core

Status: Accepted  
Date: 2026-07-16  
Sprint: 11  

## Context

Gaon must become an AI Engineering Partner, not a search interface or an automated trading bot.

The user clarified that `Learning Memory` replaces any `Research Memory` concept. Learning Memory stores not just facts, but AI experience: goals, plans, experiments, validation outcomes, success patterns, failure reasons, preferences, knowledge, citations, and conversation summaries.

## Decision

Introduce `gaon.learning` as a top-level Gaon Platform package.

The initial package contains:

- `memory`
- `evidence`
- `knowledge`
- `experience`
- `policy`
- `confidence`

The package is separate from `strategylab` so Gaon Platform capabilities can later manage StrategyLab, PluginLab, AudioLab, DevLab, LearningLab, and Memory without turning StrategyLab into the whole platform.

## Guardrails

- Learning Memory records require evidence.
- Knowledge requires evidence.
- Knowledge cannot become `Validated` without user approval.
- Policy update candidates require evidence, versionable rollback metadata, and explicit approval.
- Gaon must not autonomously modify source code, prompts, champions, secrets, trading rules, or user preferences.

## Consequences

StrategyLab remains the first research lab, while Gaon receives an independent learning core.

Future Dashboard and Telegram layers must read the same Learning State instead of each inventing its own memory model.
