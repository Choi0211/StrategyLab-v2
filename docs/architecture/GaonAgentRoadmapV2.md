# Gaon Next-Generation Architecture - Roadmap (#214 -> #219)

Gaon's long-term target is a **Conversational + Multimodal + Research +
Self-Improving AI partner**: it holds a natural conversation, knows its real
capabilities, judges what it is missing, asks for exactly what it needs, reads
external material (URLs, images, video transcripts, documents), records external
claims as *evidence* rather than fact, independently validates them against real
market data, turns validated evidence into strategy hypotheses/candidates, and -
within an approved development boundary - can inspect and modify its own code in
an isolated worktree and open a PR for human review.

This is delivered as a sequence of bounded PRs, **not** one all-in-one change.
Each PR keeps the deterministic safety boundary intact: conversation autonomy is
not execution autonomy, research autonomy is not trading authority, development
autonomy is not production authority, learning is not truth, an external claim is
not verified evidence, and an LLM's output is never a permission.

## #214 - Gaon Agent Foundation V2 (this PR)

LLM-first general conversation; recent-context / mission context switching;
deterministic multi-intent segmentation + per-segment routing; capability
registry foundation (single source of truth, honest UNAVAILABLE/FORBIDDEN);
need/gap model foundation; tool / multimodal / evidence-ingestion interface
foundations; developer-agent capability boundary. **No** real web/vision/video
provider, **no** self-code-modification, **no** production or trading authority.
See `GaonAgentFoundationV2.md`.

## #215 - Gaon Capability & Need Registry

The complete capability truth model (per-tool provenance, freshness, provider
health feeding capability state); blocker diagnosis that maps a stuck
`ResearchMission` (e.g. `strategy_hypothesis_space_exhausted`) to a concrete
`NeedAssessment`; generation of specific user-facing requests ("I need a
read-only URL provider to do this - shall I propose it as development work?");
capability-gap reasoning wired into the conversation.

## #216 - Gaon Safe Developer Agent

Isolated `git worktree` + branch; read-only repository inspection; bounded code
modification **inside the worktree only** (never the running tree); test
execution; diff self-review; commit; push; open a PR. Capabilities
`REPOSITORY_READ / CODE_MODIFY_DEV / TEST_RUN / GIT_COMMIT / GIT_PUSH /
PULL_REQUEST_CREATE` move to AVAILABLE (most APPROVAL_REQUIRED).
`MAIN_MERGE / PRODUCTION_DEPLOY / PRODUCTION_DB_WRITE / SYSTEMD_CONTROL` stay
FORBIDDEN - a human merges and deploys.

## #217 - Read-only Web & Multimodal Research Tools

Real providers behind the #214 interfaces: web search, URL fetch / reader,
document (PDF) reader, image/screenshot vision, video metadata / transcript /
frame analysis. Every result carries provider provenance and freshness. DRM /
login / private / access-denied is reported honestly. Capabilities
`WEB_SEARCH / URL_FETCH / DOCUMENT_READ / IMAGE_VISION / VIDEO_*` move to
AVAILABLE (read-only).

## #218 - Evidence Learning Pipeline

`SOURCE -> OBSERVATION -> CLAIM -> EVIDENCE -> HYPOTHESIS -> INDEPENDENT
VALIDATION -> RESULT -> CANDIDATE`. Persistent, provenance-tagged, immutable
evidence with an explicit `verification_state`; a real `EvidenceIngestor`
replacing `NullEvidenceIngestor`; independent validation runs against real KRX
data through the existing research pipeline. An unverified source can never
become a promoted strategy directly. Existing `src/gaon/knowledge/*` modules
(`claims.py`, `evidence_hypothesis.py`, `provenance.py`, `discovery.py`) are
reuse candidates and will be assessed here rather than rebuilt.

## #219 - Autonomous Research & Self-Improvement Loop

`OBSERVE -> DIAGNOSE -> CAPABILITY CHECK -> NEED ANALYSIS -> PLAN -> RESEARCH OR
DEVELOP -> VERIFY -> REPORT -> REQUEST APPROVAL IF REQUIRED -> APPLY THROUGH SAFE
CONTROLLER -> POST-VERIFY -> UPDATE CAPABILITY/EVIDENCE`. When research is
blocked, Gaon determines what is missing, runs allowed read-only external
research, produces evidence-backed hypotheses, validates them, and - if a code
change is required and development is permitted - proposes it and (with #216)
opens a PR. Promotion / LIVE / production changes still require explicit user
approval through their deterministic controllers.

## Note on numbering

No renumbering is proposed. If repo realities require adjusting a later PR's
scope, the reason will be documented in that PR's architecture note before any
code change - never folded silently into a larger PR.
