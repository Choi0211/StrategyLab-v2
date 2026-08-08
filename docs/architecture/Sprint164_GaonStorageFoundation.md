# Sprint 164 — Gaon Storage Foundation

## Goal

Separate long-lived Gaon research/knowledge data from the StrategyLab-v2
source tree and make the root configurable with `GAON_DATA_ROOT`.

## Default roots

- Windows: `D:\Gaon`
- Linux/VPS: `/var/lib/strategylab/gaon-data`

`GAON_DATA_ROOT` always overrides the platform default.

## Logical storage

- knowledge
- evidence
- memory
- experiments
- index
- cache
- archive
- logs

## Safety

External files are evidence/data only. They cannot act as instructions.

Sprint 164 does not:

- place live orders
- call KIS/Broker order APIs
- promote Champion automatically
- mutate a production strategy
- bypass human approval

## Future

Sprint 165+ will place source/provenance and knowledge-acquisition contracts
on top of this abstraction.
