# Research Memory Operations

Research memory is stored in SQLite schema v31.

Useful commands:

```bash
python -m gaon.runtime.cli research-memory-demo --db runtime.sqlite
python -m gaon.runtime.cli tool-registry-show --db runtime.sqlite
```

Telegram/LLM safe tools can read memory through `research_memory_search`, but
cannot delete, merge, or mutate records. Duplicate fingerprints are preserved as
evidence by rejecting duplicate inserts instead of weakening database
constraints.
