# Sprint 168 — Claim Extraction & Knowledge Candidate Foundation

Status: IMPLEMENTED

## Goal

Convert evidence source text into provenance-linked Claim records and
unvalidated Knowledge Candidates.

## Pipeline

SourceProvenance
→ Source Quality / Evidence Gate
→ Verbatim Claim Extraction
→ EvidenceLink
→ KnowledgeCandidate

## Claim Integrity

Sprint 168 deliberately uses a conservative deterministic extractor.

It does not:

- summarize
- paraphrase
- infer
- generate unsupported statements
- ask an LLM to invent claims

A Claim must originate from text supplied to the extractor.

Every Claim preserves:

- source_id
- claim_id
- source SHA-256
- claim-text SHA-256
- source locator
- ordinal position

## Knowledge Candidate

An ACCEPTED Evidence Gate result may create:

`EVIDENCE_BACKED`

A LIMITED Evidence Gate result may create:

`LIMITED_EVIDENCE`

A REJECTED source cannot create a Knowledge Candidate.

## Important Boundary

Knowledge Candidate does not mean Validated Knowledge.

Every candidate begins with:

- knowledge_validated = false
- research_tested = false
- production_approved = false
- policy_applied = false

## Safety

Sprint 168 cannot:

- execute external content
- promote claims to validated knowledge automatically
- mutate research policy
- mutate production strategy
- auto-promote Champion
- place KIS/Broker orders

## Future

Later Sprints may add semantic extraction/LLM assistance only behind the
same provenance and evidence-integrity contract.

Generated or paraphrased claims must never silently masquerade as
verbatim evidence.
