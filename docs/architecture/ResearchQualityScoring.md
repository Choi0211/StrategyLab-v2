# Research Quality Scoring

Sprint 98 scores candidates from 0 to 100 using configurable weights.

Components:

- performance
- robustness
- risk
- stability
- simplicity
- sample
- regime
- explainability
- novelty

Weights must cover all components and sum to 1.0. Hard failures cap the final
score so a candidate with critical evidence cannot pass by aggregate score
alone.
