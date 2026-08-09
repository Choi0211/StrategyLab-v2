# Sprint 175 - Safe Content Normalization

Status: COMPLETE

## Context

Sprint 174 downloads source bytes as inert evidence only. Sprint 175 adds the
next boundary: acquired bytes can be normalized into bounded plain text, but
external content remains evidence and never becomes executable instruction.

## Scope

- MIME-aware normalization for `text/plain`, `text/html`, and
  `application/json`.
- Structured unsupported status for `application/pdf` when no safe deterministic
  text extraction path is configured.
- Input byte and normalized text budgets.
- Stable `content-normalization:<sha256>` identity and normalized text checksum.
- Source/acquisition linkage preservation.
- `eligible_for_claim_extraction=true` only after successful textual
  normalization.

## Non-goals

- OCR.
- HTML or JavaScript execution.
- Claim extraction.
- Knowledge validation.
- Strategy mutation, Champion promotion, or trading.

## Contracts

- `knowledge_validated=false`
- `production_approved=false`
- `content_instructions_executed=false`
- Unsupported or failed content is not eligible for claim extraction.

## Release Check

```bash
python -m gaon.runtime.cli gaon-content-normalization-release-check
```

The check verifies HTML cleanup, JSON data-only extraction, PDF fail-closed
behavior, and safety flags.

## Safety

Schema remains v36. No database migration, no live trading, no KIS/Broker
orders, no Champion auto-promotion, no approval bypass, and no production
strategy mutation.
