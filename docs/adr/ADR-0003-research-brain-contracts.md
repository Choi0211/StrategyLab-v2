# ADR-0003: Research Brain Contracts

Status: Accepted  
Date: 2026-07-16  
Sprint: 11  

## Context

Sprint 11 must complete the remaining Research Brain foundation without expanding beyond the approved scope or changing the Learning Memory foundation unnecessarily.

Research Brain needs testable contracts for:

- Research Goal
- Research Planner
- Research Session
- Research Interview
- Research Journal

## Decision

Add `gaon.research` as a small package containing immutable Research Brain domain contracts.

The Research Brain contracts use existing `gaon.learning` evidence and memory types instead of creating a second memory system.

## Guardrails

- Every goal, plan, session, interview, and journal entry requires evidence.
- Research plans are deterministic and tied to a single research goal.
- Research sessions require a matching goal and plan.
- Research journals are immutable and reject duplicate entry IDs.
- Research Goal and Research Plan can export Learning Memory records.

## Non-Goals

- No V1 adapter execution.
- No live trading.
- No Telegram runtime.
- No Dashboard runtime.
- No autonomous source-code modification.

## Consequences

Research Brain can now create structured, evidence-backed research objects while preserving Learning Memory as the shared state layer for later Dashboard and Telegram integration.
