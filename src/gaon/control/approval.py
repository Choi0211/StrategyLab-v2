"""Priority 1 / C6 - explicit DEMO -> LIVE transition approval.

The one invariant this module exists for: nothing turns the bot LIVE
without a transition-scoped approval. There is deliberately NO
``set_mode(LIVE)`` / ``force_live`` / ``activate_live`` function anywhere
in ``gaon.control``.

An approval is a ONE-SHOT ticket bound to a single
``(from_mode, to_mode, intent)``. ``validate_and_consume`` fails closed -
raising a typed ``ApprovalError`` - for: unknown id, expired, wrong
transition, wrong intent, already consumed. ``require_live_approval`` is
the boolean helper the transition machine uses; any failure -> False.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from gaon.control.trading_mode import Mode

LIVE_TRANSITION_INTENT = "demo_to_live"


@dataclass(frozen=True)
class TransitionApproval:
    approval_id: str
    from_mode: Mode
    to_mode: Mode
    intent: str
    issued_at: str
    expires_at: str
    issued_by: str


class ApprovalError(Exception):
    """A transition approval could not be honoured. ``reason`` is one of:
    ``no_approval``, ``stale``, ``wrong_transition``, ``wrong_intent``,
    ``already_consumed``."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class ApprovalRegistry:
    """Issues, validates and consumes transition approvals. In-memory;
    a persistent implementation would keep the same contract."""

    def __init__(self) -> None:
        self._issued: dict[str, TransitionApproval] = {}
        self._consumed: set[str] = set()

    def issue(
        self,
        from_mode: Mode,
        to_mode: Mode,
        intent: str,
        *,
        now: str,
        ttl_seconds: int,
        issued_by: str,
    ) -> TransitionApproval:
        approval_id = f"approval:{uuid4().hex}"
        expires = _parse(now) + timedelta(seconds=max(1, int(ttl_seconds)))
        ticket = TransitionApproval(
            approval_id=approval_id,
            from_mode=from_mode,
            to_mode=to_mode,
            intent=intent,
            issued_at=now,
            expires_at=expires.isoformat().replace("+00:00", "Z"),
            issued_by=issued_by,
        )
        self._issued[approval_id] = ticket
        return ticket

    def is_consumed(self, approval_id: str) -> bool:
        return approval_id in self._consumed

    def validate_and_consume(
        self,
        approval_id: str,
        from_mode: Mode,
        to_mode: Mode,
        intent: str,
        *,
        now: str,
    ) -> TransitionApproval:
        ticket = self._issued.get(approval_id)
        if ticket is None:
            raise ApprovalError("no_approval", "no such transition approval")
        if approval_id in self._consumed:
            raise ApprovalError("already_consumed", "this transition approval was already used")
        if _parse(now) > _parse(ticket.expires_at):
            raise ApprovalError("stale", "this transition approval has expired")
        if ticket.from_mode is not from_mode or ticket.to_mode is not to_mode:
            raise ApprovalError("wrong_transition", "approval is for a different mode transition")
        if ticket.intent != intent:
            raise ApprovalError("wrong_intent", "approval is for a different intent")
        self._consumed.add(approval_id)
        return ticket


def require_live_approval(registry: ApprovalRegistry, approval_id: str, *, now: str) -> bool:
    """True only if ``approval_id`` is a currently-valid, unconsumed
    DEMO -> LIVE approval with the LIVE transition intent; consumes it.
    Any problem -> False (fail closed). This is the ONLY sanctioned way to
    let a DEMO -> LIVE transition proceed."""
    try:
        registry.validate_and_consume(approval_id, Mode.DEMO, Mode.LIVE, LIVE_TRANSITION_INTENT, now=now)
        return True
    except ApprovalError:
        return False
