# Research Approval Flow

Status: Sprint 16 foundation

Research approval is explicit and token-scoped.

## Flow

1. User asks for a research plan.
2. Gaon creates a deterministic `ResearchProposal`.
3. Gaon creates an `ApprovalRequest` with proposal ID, actor, chat ID, token, and expiry.
4. User approval must include the matching proposal and token.
5. Wrong actor, wrong chat, wrong token, duplicate state, and expired approvals are rejected.
6. Approved runs may enter `running`; no approval means no running state.

## Current Limitations

- Queue is in-memory only.
- No autonomous loop.
- No actual backtest execution.
- No automatic Learning Memory save.
- No production deployment is started by this sprint.
