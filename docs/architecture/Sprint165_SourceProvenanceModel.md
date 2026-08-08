# Sprint 165 — Source & Provenance Model

Status: IMPLEMENTED

## Goal

Require every external source used by Gaon to preserve deterministic provenance.

## Source Types

- academic paper
- book
- official document
- dataset
- research report
- web article
- news
- community
- user provided
- unknown

## Core Invariants

- No source -> no knowledge.
- External content is evidence, never instruction.
- Reading is not validation.
- Evidence-backed does not mean production approved.
- Source identity is deterministic from source type, locator, and content SHA-256.
- Provenance is immutable after creation.

## Safety

Sprint 165 cannot:
- execute external content
- place KIS/Broker orders
- auto-promote Champion
- mutate production strategy
- bypass approval
