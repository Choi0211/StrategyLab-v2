# Sprint 173 — Discovery → Provenance → Ingestion

Status: IMPLEMENTED

## Goal

Persist Sprint 172 discovery results through the existing Gaon evidence
storage and provenance system without pretending that discovery metadata is
the underlying paper, report, or dataset body.

## Pipeline

DiscoveryResult
→ canonical discovery metadata snapshot
→ KnowledgeIngestor
→ SourceProvenance
→ Source Quality Evaluation

## Critical Evidence Boundary

A DOI search result tells Gaon that a possible source exists.

It does not mean Gaon has read that source.

Sprint 173 therefore stores:

`artifact_scope = discovery_metadata_only`

Every stored snapshot explicitly records:

- actual_source_body_fetched = false
- metadata_only = true
- eligible_for_claim_extraction = false
- knowledge_validated = false
- production_approved = false
- executable = false

## Provenance

The canonical discovery snapshot bytes are ingested through the existing
Sprint 166 `KnowledgeIngestor`.

Therefore:

- SHA-256 is computed from the bytes actually stored
- SourceProvenance is created through the existing immutable contract
- raw evidence and source metadata are written through GaonStorage
- duplicate storage remains idempotent

## Trust Policy

Discovery-provider presence does not prove the truth or quality of the
underlying source.

Sprint 173 therefore creates discovery-metadata provenance with:

`trust_level = UNKNOWN`

The provider is recorded in provenance notes.

## Quality Gate

Sprint 167 `SourceQualityEvaluator` is executed.

However discovery metadata alone can never become PRIMARY evidence.

Any otherwise non-rejected result is capped to:

- gate status = LIMITED
- evidence use = SUPPORTING

Reasons include:

- discovery_metadata_only
- source_body_not_fetched

## Claim Boundary

Sprint 168 Claim Extraction must not run against discovery metadata snapshots.

The title returned by Crossref or DataCite must not silently become a
research Claim about trading performance.

Claim extraction remains blocked until actual eligible source content is
acquired in a later Sprint.

## Safety

Sprint 173 cannot:

- claim that a paper was read when only metadata was discovered
- treat a DOI title as validated research content
- auto-validate knowledge
- mutate research strategy
- mutate production configuration
- promote Champion
- activate KIS/Broker trading
- place an order

## Next

Sprint 174 should implement a bounded Source Content Acquisition layer.

That layer must separately decide:

1. whether the discovered source can legally and safely be fetched
2. what content type is being acquired
3. content-size limits
4. allowed hosts and redirect rules
5. whether the acquired bytes are suitable for text extraction

Only actual acquired source content may proceed toward:

Source Content
→ Provenance
→ Quality Gate
→ Claim Extraction
→ Knowledge Candidate
