# Strategy Handoff Package

Sprint 48 adds an approved Champion handoff boundary for StrategyLab.

The package is a deterministic JSON artifact created from:

- the active Champion registry entry
- the source BacktestResult
- the LIVE_ELIGIBLE PaperRevalidationReport
- policy versions and compatibility metadata

Package generation is not deployment authorization. A package starts as
`pending_approval`; explicit human approval is required before its status can
become `approved_for_deployment`.

Safety boundaries:

- no executable Python code
- no shell commands
- no broker credentials
- no account identifiers
- no private repository paths or imports
- no automatic handoff from HOLD, KILL, or ROLLBACK_RECOMMENDED

The checksum is calculated from canonical JSON with the manifest checksum field
blanked. If any package content changes, the checksum changes and any prior
approval no longer applies to the new content.
