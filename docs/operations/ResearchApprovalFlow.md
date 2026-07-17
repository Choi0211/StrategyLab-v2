# Research Approval Flow

Status: Sprint 18 hardened approval foundation

Research approval is explicit, token-scoped, and single-use.

## Flow

1. User asks for a research plan.
2. Gaon creates a deterministic `ResearchProposal`.
3. Gaon creates an `ApprovalRequest` with proposal ID, approval ID, actor, chat ID, issued time, expiry, nonce, and an HMAC-SHA256 token digest.
4. Raw approval tokens are never stored in SQLite, logs, audit payloads, fixtures, or exceptions.
5. User approval must include the matching proposal, approval ID, actor, chat ID, and token.
6. Approval states are `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `CONSUMED`, and `CANCELLED`.
7. Starting a run consumes an approved record and binds it to the target run ID.
8. Replay, token tampering, cross-proposal use, cross-chat use, cross-actor use, and expired approvals are rejected.

## Current Limitations

- Queue is in-memory only until the SQLite repository layer is completed.
- Durable approval storage is introduced in the repository hardening sprint.
- No actual backtest execution.
- No automatic Learning Memory save.
- No production deployment is started by this sprint.
