# Sprint 166 — Knowledge Acquisition Foundation

Status: IMPLEMENTED

## Goal

Safely ingest external source bytes into Gaon's configurable long-term storage.

Sprint 166 does not browse the Internet yet.

It accepts externally supplied/provider supplied bytes and stores:

1. immutable raw evidence
2. SHA-256 checksum
3. Source Provenance
4. source metadata
5. duplicate/idempotency state

## Storage

Raw source:
`evidence/raw/`

Metadata:
`index/sources/`

## Security Boundary

All external content is:

`UNTRUSTED EVIDENCE`

It is never interpreted as system instruction or executable code.

The ingestion layer sets:

- executable = false
- knowledge_validated = false
- production_approved = false

## Budget

`GAON_MAX_SOURCE_BYTES` limits individual source size.

Default:
25 MiB

## Not Included

- web browsing
- automatic downloading
- PDF semantic extraction
- knowledge promotion
- hypothesis promotion
- Champion promotion
- live trading
- KIS/Broker orders
