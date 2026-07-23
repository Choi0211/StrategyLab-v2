# Research Self Critic

Sprint 91 adds a deterministic advisory critic for strategy research results.

The critic evaluates overfit gaps, sample size, trade count, out-of-sample
stability, drawdown, parameter stability, regime dependency, liquidity
assumptions, feature complexity, suspicious performance, walk-forward
instability, and Monte Carlo fragility.

Decisions are `pass`, `pass_with_warnings`, `needs_revision`, and `reject`.
Each finding includes a code, severity, evidence references, and a recommended
action. The critic cannot promote a Champion, place orders, change code, or
mutate production configuration.
