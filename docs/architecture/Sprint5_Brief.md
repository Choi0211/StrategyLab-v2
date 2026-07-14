# StrategyLab v2 Sprint 5 Brief

Sprint ID: Sprint 5  
Sprint Name: Portfolio Engine  
Status: Planned  
Date: 2026-07-14  
Depends On: Sprint 4 Backtest v2

## Objective

Build portfolio accounting foundations: cash, positions, allocations, fixed-size position sizing, rebalancing instructions, and performance snapshots.

## In Scope

- Cash ledger model.
- Position model.
- Portfolio state model.
- Allocation target model.
- Fixed position sizing helper.
- Rebalancing instruction generator.
- Portfolio performance snapshot.
- Unit tests and documentation.

## Out of Scope

- Broker orders.
- Live account reconciliation.
- Risk scoring.
- Multi-currency accounting.
- Tax handling.
- Execution routing.

## Acceptance Criteria

- Cash debits/credits are deterministic.
- Positions update from buy/sell quantities.
- Holdings value is calculated from price marks.
- Allocation targets validate to 100%.
- Rebalance instructions compare current value with target value.
- Tests pass and documentation is updated.

