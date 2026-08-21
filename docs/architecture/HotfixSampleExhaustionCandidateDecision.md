# Hotfix: Sample Exhaustion Candidate Decision

Status: IMPLEMENTED

## Context

Production Research Mission continuation reached a valid cumulative sample
state for `KR-ST-005`:

- cumulative attempted symbols: 33
- cumulative valid symbols: 32
- cumulative trades: 201
- latest batch: 5 valid symbols / 28 trades
- adaptive sampling stop reason: `candidate_pool_exhausted`

The candidate still rendered as `collect_more_evidence` and the Telegram
response kept asking for more representative non-duplicate symbols. That
was incorrect once the provider/universe pool had already reported no new
independent symbols.

## Root Cause

The mission recorded breadth evidence cumulatively, but did not persist the
adaptive-sampling exhaustion reason on `StrategyCandidateRecord`. The next
continuation turn only saw an active candidate with no pending robustness
focus and re-entered `EXPAND_SAMPLE`.

Monte Carlo eligibility also risked being interpreted from the latest
batch-local sample instead of the canonical cumulative candidate evidence.

## Design

`StrategyCandidateRecord` now preserves:

- `sample_exhaustion_reason`
- `breadth_summary`
- canonical symbol-keyed breadth evidence, including ineligible excluded
  symbols for attempted-symbol accounting

`next_blocker_driven_research_action()` treats sample exhaustion as a
decision boundary:

- if cumulative evidence is sufficient, the candidate is evaluated through
  the next validation dimension such as OOS, regime, walk-forward, cost,
  sensitivity, or Monte Carlo;
- if cumulative evidence is still insufficient and the pool is exhausted,
  the candidate rotates instead of repeating `EXPAND_SAMPLE`;
- if all robustness symbols are already consumed after pool exhaustion, the
  candidate rotates and the existing strategy-space expansion path remains
  available.

The Telegram mission continuation path checks the persisted exhaustion
state before starting a new breadth cycle. It either dispatches the next
robustness action or rotates the candidate; it does not silently call
`multi_symbol_research` again for the same exhausted pool.

## Batch Versus Cumulative

The multi-symbol renderer now labels per-run output as a batch and points
mission decisions at the canonical cumulative candidate state. A latest
batch such as `5 symbols / 28 trades` can be displayed without replacing
the candidate's authoritative `32 symbols / 201 trades` evidence.

## Invariants

- Mission target remains `promotion-ready candidates: 0/3`, not `0/1`.
- Candidate history is preserved across restart.
- Candidate creation or sample exhaustion is not promotion progress.
- Unregistered data-quality failures remain fail-closed.
- No live trading, broker/KIS order, Champion auto-promotion, approval
  bypass, strategy mutation, or fabricated metrics are added.
- Schema remains v36.

## Release Check

`gaon-production-sample-exhaustion-candidate-decision-release-check` proves:

- cumulative sample state is `32 valid / 33 attempted / 201 trades`;
- latest batch state remains separately visible as `5 valid / 28 trades`;
- `candidate_pool_exhausted` persists through JSON restart;
- `EXPAND_SAMPLE` is not repeated after pool exhaustion;
- Monte Carlo eligibility uses cumulative trade count;
- exhausted candidates can rotate and strategy-space expansion stays
  available;
- read-only queries do not execute research tools;
- safety boundaries remain unchanged.
