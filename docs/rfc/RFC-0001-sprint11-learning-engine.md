# RFC-0001: Sprint 11 Learning Engine Foundation

Status: Accepted for Sprint 11  

## Problem

StrategyLab needs a stable foundation for Gaon to learn from research activity without becoming an unsafe autonomous trading or self-modifying system.

## Proposal

Add `gaon.learning` with testable domain contracts:

- evidence records
- learning memory records
- knowledge lifecycle
- experience patterns
- policy update candidates
- confidence scores

## Non-Goals

- No AI provider calls.
- No Telegram runtime.
- No Dashboard runtime.
- No broker calls.
- No MyMoneyGuard private integration.
- No source-code automation.

## Validation

Sprint 11 validation starts with unit tests that prove:

- Learning Memory requires evidence.
- Knowledge cannot be auto-validated.
- Policy updates need evidence and rollback metadata.
- Forbidden autonomous actions are explicit.

Integration with StrategyLab research pipelines is reserved for later sprints.
