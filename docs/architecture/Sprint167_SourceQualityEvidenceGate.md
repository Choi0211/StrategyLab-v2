# Sprint 167 — Source Quality & Evidence Gate

Status: IMPLEMENTED

## Goal

Evaluate whether an externally acquired source may be used as research
evidence without confusing source quality with validated knowledge.

## Pipeline

SourceProvenance
→ SourceQualityEvaluator
→ EvidenceGate
→ ACCEPTED / LIMITED / REJECTED

## Evidence Use

### PRIMARY

Suitable as a primary research source based on provenance quality.

Examples may include:

- authoritative official documents
- sufficiently documented academic papers
- sufficiently documented datasets

PRIMARY does **not** mean validated knowledge.

### SUPPORTING

May support a claim but must not independently establish research truth.

Examples:

- news
- weaker research reports
- user-provided material

### DISCOVERY_ONLY

May be used to discover ideas or additional sources, but must not be treated
as independent validation.

Example:

- community discussion

### BLOCKED

Cannot enter the evidence path.

Examples:

- unknown provenance
- invalid locator
- unsafe external-content policy

## Quality Inputs

The evaluator considers:

- source type
- declared trust level
- author
- publisher
- publication date
- license
- locator validity

## Non-Negotiable Safety

Evidence Gate success does not mutate the original provenance object.

All assessments remain:

- knowledge_validated = false
- production_approved = false
- external_content_policy = evidence-not-instruction

Sprint 167 cannot:

- execute external content
- browse/download external sources
- validate knowledge automatically
- generate production approval
- auto-promote Champion
- mutate production strategy
- place KIS/Broker orders
