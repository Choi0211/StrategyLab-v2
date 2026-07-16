# StrategyLab v2.0 Foundation Release Candidate Notes

Status: Release Candidate Foundation  
Base: StrategyLab v1.0 Stable Release

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
