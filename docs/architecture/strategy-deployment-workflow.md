# Strategy Deployment Workflow

Sprint 49 adds an approval-gated deployment workflow for Strategy Handoff
Packages.

Hard preconditions:

- handoff package exists
- package status is `approved_for_deployment`
- latest approval checksum matches the package checksum
- active Champion version and fingerprint still match the package manifest
- adapter health check passes
- target compatibility check passes

The workflow runs:

1. deployment request
2. preflight
3. mandatory backup
4. mandatory dry-run
5. apply package
6. restart or reload
7. verify active strategy
8. automatic rollback if a modified target cannot be verified

The public repository includes `FakeStrategyDeploymentAdapter` and a bounded
`LocalSafeStrategyDeploymentAdapter`. It does not include private broker,
server, or production runtime adapters.
