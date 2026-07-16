# ADR-0009: Report Scheduler

Status: Accepted  
Sprint: Runtime Collaboration

Daily and weekly jobs use explicit reference times in tests. The in-memory scheduler prevents duplicate same-day runs by idempotency key.

OS cron, systemd, VPS runner setup, and persistent job storage are out of scope for this phase.
