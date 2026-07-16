# Learning Memory

Status: Sprint 11 Foundation

Learning Memory is the system where Gaon accumulates evidence-backed experience.

It is not a simple storage layer.

## Required Memory Categories

- Research Goal
- Research Plan
- Experiment
- Backtest Result
- Validation Result
- Failure Reason
- Success Pattern
- User Preference
- Knowledge
- Citation
- Conversation Summary

## Evidence Rule

Every Learning Memory record requires evidence.

Evidence may come from:

- Source
- URL
- Document
- Research
- Paper
- Official Documentation
- Backtest
- Experiment

## Knowledge Rule

Knowledge lifecycle:

```text
Collected
  -> Reviewed
  -> Need Validation
  -> Validated
  -> Deprecated
```

`Validated` requires user approval.

## Policy Rule

Policy changes are candidates until approved by the user.

Every policy update candidate requires:

- evidence
- rollback reference
- approval record

## Forbidden Autonomous Actions

Gaon must not autonomously:

- modify source code
- change prompts
- operate champions
- change secrets
- change trading rules
- delete user preferences
