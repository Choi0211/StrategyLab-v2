# Sprint 174 — Bounded Source Content Acquisition

Status: IMPLEMENTED

## Goal

Safely acquire actual bytes for a source discovered in Sprint 172/173.

## Critical Identity Boundary

A discovery locator such as a DOI is not automatically the content body.

Sprint 174 separates:

- source_locator
- content_url

The caller must provide the actual content URL.

## Supported Content Types

Initial allowlist:

- text/plain
- text/html
- application/json
- application/pdf

All other MIME types fail closed.

Sprint 174 stores bytes only.

It does not parse HTML, extract PDF text, execute JSON, or run scripts.

## Network Policy

Network execution is disabled by default.

When enabled, acquisition requires:

- HTTPS
- explicit hostname allowlist
- standard HTTPS port
- no URL credentials
- public destination
- timeout
- maximum byte budget
- same-host redirects only

Private, loopback, link-local, reserved and other non-public destinations
are blocked.

## Storage

Acquired bytes enter the existing Sprint 166 KnowledgeIngestor.

Therefore the actual stored bytes receive:

- SHA-256
- immutable SourceProvenance
- raw evidence path
- metadata path
- untrusted evidence policy
- executable=false
- knowledge_validated=false
- production_approved=false

## Claim Boundary

Successful content acquisition means the source bytes exist.

It does not yet mean they are suitable for Claim Extraction.

Sprint 174 therefore keeps:

`eligible_for_claim_extraction = false`

Text normalization / HTML extraction / PDF text extraction and content
integrity validation belong to the next layer.

## Safety

Sprint 174 cannot:

- interpret downloaded instructions
- execute downloaded content
- claim a PDF/HTML page says something before parsing
- validate knowledge
- mutate strategy configuration
- promote Champion
- activate KIS/Broker live trading
- place orders

## Next

Sprint 175 should implement Safe Content Normalization.

Expected pipeline:

Acquired bytes
→ MIME-aware safe parser
→ normalized source text
→ content integrity checks
→ Claim Extraction eligibility

PDF/HTML extraction must remain non-executable and deterministic where
possible.
