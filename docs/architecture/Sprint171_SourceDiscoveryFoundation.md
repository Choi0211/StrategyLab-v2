# Sprint 171 — Source Discovery Foundation

Status: IMPLEMENTED

## Goal

Convert Sprint 170 Research Questions into deterministic and bounded
Source Discovery Plans.

Sprint 171 does not access the Internet.

## Pipeline

Research Question
→ Discovery Planner
→ Query Budget
→ Provider Policy
→ Source-Type Policy
→ Discovery Queries

Future network discovery must then continue through:

Discovery Result
→ Source Provenance
→ Raw Evidence Ingestion
→ Source Quality Gate
→ Claim
→ Knowledge Candidate
→ Conflict Re-evaluation

No discovery result may bypass this chain.

## Default Allowed Source Types

- academic paper
- official document
- dataset
- research report

News and community content are not part of the default research-grade
discovery policy.

They may be added later only as lower-quality supporting/discovery evidence.

## Default Providers

- academic search
- official web
- dataset catalog

`GENERAL_WEB` exists as a contract but is not enabled by default.

## Budget

Default:

- max queries: 4
- max results per query: 10
- max total results: 25

Invalid budgets fail closed.

## Duplicate Protection

Each query receives a deterministic identifier based on:

- research question ID
- provider
- normalized query

Duplicate discovery queries therefore collapse to the same identity.

## Safety

Sprint 171 explicitly keeps:

- network_executed=false
- auto_ingest=false
- auto_validate=false
- knowledge_validated=false
- production_approved=false
- execution_authorized=false

Sprint 171 cannot:

- access the Internet
- download sources
- execute external content
- ingest automatically
- validate knowledge automatically
- mutate strategy
- promote Champion
- enable KIS/Broker live trading
- place orders

## Next

Sprint 172 may implement bounded provider execution.

Provider results must remain untrusted discovery results and must enter
Sprint 165+ provenance/evidence processing before they can affect research.
