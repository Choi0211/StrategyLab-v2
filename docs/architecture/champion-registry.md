# Champion Registry and Approval Promotion

Sprint 44 adds a Champion Strategy Registry for StrategyLab. The registry records which strategy version is the current Champion for a stable slot, currently `default`.

The registry is state and history only. It does not connect to live KIS, broker orders, active strategy switching, or automatic trading.

## Flow

```text
Backtest
-> Validation
-> Champion / Challenger Evaluation
-> PROMOTION_CANDIDATE
-> Promotion Request
-> Explicit Human Approval
-> Champion Registry Activation
-> Champion Version History
```

`PROMOTION_CANDIDATE` never directly activates a Champion. A promotion request is required, and activation happens only after explicit approval.

## Domain

- `ChampionRegistryEntry`: active Champion view for a slot.
- `ChampionStrategyVersion`: immutable version history record.
- `PromotionRequest`: approval-gated request created from a Sprint 43 evaluation.
- `PromotionDecisionRecord`: explicit approve/reject audit record.
- `ChampionRollbackRequest`: explicit admin rollback request.
- `ChampionRollbackResult`: rollback outcome.

## Preconditions

A promotion request is accepted only when:

- Sprint 43 evaluation exists.
- Evaluation decision is `promotion_candidate`.
- Champion and Challenger fingerprints exist.
- Challenger fingerprint differs from the current Champion fingerprint.
- The candidate is not already the active Champion.

`keep_champion`, `review`, missing evaluation, missing fingerprints, and already active fingerprints are rejected.

## Persistence

Schema v15 adds:

- `champion_registry`
- `champion_history`
- `promotion_requests`
- `promotion_decisions`

All migrations are forward-only and non-destructive.

## Events And Metrics

Events:

- `ChampionBootstrapCreated`
- `ChampionPromotionRequested`
- `ChampionPromotionApproved`
- `ChampionPromotionRejected`
- `ChampionActivated`
- `ChampionRollbackRequested`
- `ChampionRolledBack`

Metrics:

- `gaon_champion_promotion_requests_total`
- `gaon_champion_promotions_approved_total`
- `gaon_champion_promotions_rejected_total`
- `gaon_champion_activations_total`
- `gaon_champion_rollbacks_total`

## Safety

No live trading side effects are introduced. The registry does not import or call live broker code, KIS integrations, MyMoneyGuard, or paid providers.
