# Real Autonomous Research

Sprint 120 composes the real research pipeline:

User request -> Strategy Parser -> Market Data Provider -> Data Quality ->
Rule Backtest -> Walk-Forward Validation -> Evidence Critic -> Candidate
Generator -> Candidate Backtests -> Comparison -> Research Memory -> Korean
Report.

The pipeline is read-only and advisory. It persists research memory with
strategy fingerprint, dataset fingerprint, backtest run, metrics, critic
findings, improvement candidates, comparison, source, and timestamp.

Safety boundaries remain unchanged: no live KIS, no broker order, no automatic
Champion promotion, no approval bypass, no arbitrary shell/SQL, and no
LLM-generated Python execution.
