# Research Iteration Loop

Sprint 93 introduces a bounded loop:

Strategy Candidate -> Critique -> Improvement Plan -> Revised Candidate ->
Quality Score -> Stop or Continue.

The default maximum is three iterations. The loop is deterministic, immutable,
and stops when target quality is reached, a clean pass is found, there is no
meaningful improvement, or the configured iteration cap is reached.

The loop improves only strategy hypotheses and research parameters. It does not
edit Python source, call shell commands, alter git state, change live trading
configuration, or approve deployment.
