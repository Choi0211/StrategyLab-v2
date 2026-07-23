# Research Memory

Sprint 95 adds persistent SQLite research memory for self-improving research.

Memory entries store strategy family, market, timeframe, hypothesis, result
summary, critic summary, improvement summary, final status, tags, source run,
source references, and a deterministic fingerprint.

The fingerprint prevents duplicate memory rows. Search supports strategy
family, market, timeframe, tag, and free text over hypothesis, summaries, and
tags. Existing records are preserved; no automatic merge or deletion is
performed.

Schema v31 adds `research_memories`, `strategy_lineage`,
`research_critiques`, `research_iterations`, `research_quality_scores`,
`research_concepts`, and `research_concept_relationships`.
