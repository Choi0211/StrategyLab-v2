# Portfolio Engine

Status: Sprint 5 Foundation

## Purpose

The Portfolio Engine tracks cash, positions, allocation targets, rebalancing instructions, and performance snapshots.

## Contracts

- `CashLedger`: deterministic cash debit/credit.
- `Position`: quantity and average price.
- `PortfolioState`: cash plus positions.
- `AllocationTarget`: target symbol weight.
- `RebalanceInstruction`: current value, target value, and delta value.
- `PerformanceSnapshot`: cash, holdings value, and total equity.
- `FixedQuantitySizer`: minimal fixed-quantity sizing helper.

## Non-Goals

Sprint 5 does not place broker orders, reconcile live holdings, calculate risk scores, or implement multi-currency accounting.

