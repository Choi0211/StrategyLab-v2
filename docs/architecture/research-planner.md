# Research Planner

Status: Phase B Sprint 30

Research planning is deterministic and free-only by default.

The planner creates bounded `ResearchPlan` objects from `ResearchRequest` and `ResearchStep` contracts. Step tools are allowlisted and dependency graphs reject missing steps, cycles, excessive dependency depth, and excessive step count.

Supported step types:

- memory_search
- web_search
- rss_fetch
- repository_search
- evidence_filter
- context_build
- synthesis
- knowledge_proposal
- report_render

Provider-backed planning is optional and must pass structured-output validation. Free-only mode prevents silent fallback to paid providers.
