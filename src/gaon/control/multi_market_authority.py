"""Market-specific Gaon autonomy authority: pure fail-closed policy.

Equities: candidate discovery may be autonomous, activation requires a
human approval bound to exact market/account/strategy version.
Binance: paper autonomy may research and simulate; live requires a
separate explicit live AI authorization, in addition to strategy approval.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

MARKETS = frozenset({"KR_STOCK", "US_STOCK", "BINANCE"})
MODES = frozenset({"paper", "live"})

@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str

def _valid_approval(approval, *, market, account, version, now=None):
    if not isinstance(approval, dict):
        return False
    if approval.get("status") != "approved" or approval.get("market") != market:
        return False
    if approval.get("account") != account or approval.get("strategy_version_id") != version:
        return False
    if not isinstance(approval.get("approved_by"), str) or not approval["approved_by"].strip():
        return False
    if not isinstance(approval.get("approval_id"), str) or not approval["approval_id"].strip():
        return False
    try:
        issued = datetime.fromisoformat(approval["approved_at"])
        if issued.tzinfo is None:
            return False
        return issued <= (now or datetime.now(timezone.utc))
    except (KeyError, TypeError, ValueError):
        return False

def may_activate_strategy(*, market, account, strategy_version_id, approval=None):
    """Precondition only. Caller must verify approval provenance independently."""
    if market not in MARKETS or not account or not strategy_version_id:
        return PolicyDecision(False, "invalid_scope")
    if not _valid_approval(approval, market=market, account=account,
                           version=strategy_version_id):
        return PolicyDecision(False, "explicit_strategy_approval_required")
    return PolicyDecision(True, "approval_fields_match_requires_provenance_verification")

def may_execute_ai(*, market, mode, account, strategy_version_id,
                   strategy_approval=None, live_ai_approval=None):
    if market not in MARKETS or mode not in MODES or not account or not strategy_version_id:
        return PolicyDecision(False, "invalid_scope")
    if market in {"KR_STOCK", "US_STOCK"}:
        return PolicyDecision(False, "equities_use_approved_strategy_engine_not_direct_ai_orders")
    if mode == "paper":
        return PolicyDecision(False, "paper_execution_adapter_not_integrated")
    if not _valid_approval(strategy_approval, market=market, account=account,
                           version=strategy_version_id):
        return PolicyDecision(False, "strategy_approval_required")
    if not _valid_approval(live_ai_approval, market=market, account=account,
                           version=strategy_version_id):
        return PolicyDecision(False, "separate_live_ai_approval_required")
    return PolicyDecision(False, "live_ai_execution_not_validated")
