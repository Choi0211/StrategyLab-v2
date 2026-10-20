"""Deterministic, non-LLM failure-analysis and hypothesis generation for
the Gaon<->Paper feedback loop (see ``gaon.runtime.paper_observation_repository``
for the ledger this reads, ``gaon.runtime.paper_failure_hypothesis_repository``
for where its output is stored, and ``scripts/generate_paper_failure_hypotheses.py``
for the orchestration script that wires the two together on a timer).

What this does: given a family's closed Paper trades, compare win vs loss
characteristics (symbol concentration, fee burden, early-exit vs
scheduled-exit outcome) and propose a bounded, explicitly-labeled set of
improvement hypotheses. Every comparison that lacks enough data to be
meaningful is reported as ``status="insufficient_evidence"`` rather than
silently skipped or forced - this module never pretends to have found a
pattern it does not have enough trades to support.

What this does NOT do - by design, so a later module can be added without
changing this one:
  - it never backtests anything (a future ``backtest_hypothesis(hypothesis)``
    would take a ``status="candidate"`` Hypothesis and replay history with
    the implied parameter change);
  - it never schedules a fresh Paper forward-verification run (a future
    module would, only on a backtest PASS, do that - mirroring
    ``scripts/register_csm_48h_long.py``'s own one-off, reviewed pattern);
  - it never touches ``strategy_version_registries`` or promotes anything -
    even a fully-validated hypothesis still requires the existing
    human-approval-gated ``activate_strategy_version()`` path, no bypass.
Each ``Hypothesis.verification_required`` entry spells out exactly what
independent evidence a human (or a future automated stage) still needs
before any of that - this module's only job is to say what looks
suspicious, how confident that claim is, and what evidence is missing,
or to say plainly that there isn't enough data yet.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Below this many TOTAL closed trades, no comparison for this family is
# attempted at all - every pattern collapses into one explicit
# "insufficient_evidence" hypothesis naming the shortfall.
MIN_TOTAL_TRADES = 10
# Below this many trades in EACH side of a two-group comparison (e.g. win
# vs loss, early-exit vs scheduled-exit), that specific comparison is
# reported as insufficient_evidence rather than attempted.
MIN_GROUP_TRADES = 5
# Heuristic sample-size-based confidence saturates to 1.0 at this many
# trades. This is NOT a statistical significance test (no p-value, no
# confidence interval) - it is a transparent, linear "how much evidence
# backs this" signal meant for human prioritization only.
CONFIDENCE_SATURATION_TRADES = 30

# Matches the research's own promotion-gate concentration threshold
# (single-symbol <= 40% of net profit) - reusing the same number the
# strategy's own due-diligence already used, not inventing a new one.
SYMBOL_CONCENTRATION_THRESHOLD = 0.40
# Fees eating more than this fraction of mean |gross pnl| magnitude is
# flagged as material cost drag.
FEE_DRAG_THRESHOLD = 0.30
# Minimum absolute win-rate gap between early-exit and scheduled-exit
# trades to flag a pattern (not just sampling noise at the margin).
EARLY_EXIT_WIN_RATE_GAP_THRESHOLD = 0.30

INSUFFICIENT_EVIDENCE = "insufficient_evidence"
CANDIDATE = "candidate"


@dataclass(frozen=True)
class TradeRecord:
    """One closed trade, normalized from a `paper_trade_observations` row.

    `gross_pnl` is the reported `pnl` field (pre-fee, from the position's
    mark-price movement). `net_pnl` is `gross_pnl + fees` only when BOTH
    are known - never estimated. `pnl_basis` says which one `is_win` was
    actually computed from, so a caller never silently treats an estimate
    as a confirmed value."""

    symbol: str
    entry_at: str | None
    exit_at: str | None
    entry_price: float | None
    exit_price: float | None
    qty: float | None
    gross_pnl: float | None
    fees: float | None
    net_pnl: float | None
    pnl_pct: float | None
    holding_hours: float | None
    reason: str | None
    pnl_basis: str | None  # "net" | "gross_fallback" | None (no pnl known at all)
    is_win: bool | None


@dataclass(frozen=True)
class Hypothesis:
    family_id: str
    pattern_type: str
    hypothesis_id: str
    fingerprint: str
    status: str  # INSUFFICIENT_EVIDENCE | CANDIDATE
    statement: str
    trade_count: int
    confidence: float | None
    evidence: Mapping[str, object]
    expected_improvement: str | None
    verification_required: tuple[str, ...] = field(default_factory=tuple)
    generated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "pattern_type": self.pattern_type,
            "hypothesis_id": self.hypothesis_id,
            "fingerprint": self.fingerprint,
            "status": self.status,
            "statement": self.statement,
            "trade_count": self.trade_count,
            "confidence": self.confidence,
            "evidence": dict(self.evidence),
            "expected_improvement": self.expected_improvement,
            "verification_required": list(self.verification_required),
            "generated_at": self.generated_at,
        }


_STANDARD_VERIFICATION_STEPS = (
    "historical backtest with the implied parameter/rule change applied",
    "independent Paper forward re-run accumulating its own sufficient trade count",
    "human review before any Live consideration",
)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _holding_hours(entry_at: str | None, exit_at: str | None) -> float | None:
    start, end = _parse_iso(entry_at), _parse_iso(exit_at)
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 3600.0, 4)


def collect_trade_records(observations: Sequence[Mapping[str, object]]) -> list[TradeRecord]:
    """Normalizes closed `paper_trade_observations` rows into `TradeRecord`s.
    Skips any row whose `status` is not `closed` - open/signal/rejected
    rows carry no realized outcome to analyze. Never fabricates a missing
    value: a field that wasn't reported stays `None`, and `pnl_basis`
    records which (if any) pnl figure `is_win` actually used."""
    records: list[TradeRecord] = []
    for obs in observations:
        if obs.get("status") != "closed":
            continue
        gross_pnl = _as_float(obs.get("pnl"))
        fees = _as_float(obs.get("fees"))
        net_pnl = (gross_pnl + fees) if (gross_pnl is not None and fees is not None) else None
        if net_pnl is not None:
            pnl_basis, is_win = "net", net_pnl > 0
        elif gross_pnl is not None:
            pnl_basis, is_win = "gross_fallback", gross_pnl > 0
        else:
            pnl_basis, is_win = None, None
        records.append(
            TradeRecord(
                symbol=str(obs.get("symbol") or ""),
                entry_at=_as_opt_str(obs.get("entry_at")),
                exit_at=_as_opt_str(obs.get("exit_at")),
                entry_price=_as_float(obs.get("entry_price")),
                exit_price=_as_float(obs.get("exit_price")),
                qty=_as_float(obs.get("qty")),
                gross_pnl=gross_pnl,
                fees=fees,
                net_pnl=net_pnl,
                pnl_pct=_as_float(obs.get("pnl_pct")),
                holding_hours=_holding_hours(_as_opt_str(obs.get("entry_at")), _as_opt_str(obs.get("exit_at"))),
                reason=_as_opt_str(obs.get("reason")),
                pnl_basis=pnl_basis,
                is_win=is_win,
            )
        )
    return records


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _fingerprint(family_id: str, pattern_type: str, evidence: Mapping[str, object]) -> str:
    canonical = json.dumps({"family_id": family_id, "pattern_type": pattern_type, "evidence": evidence}, sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _confidence(trade_count: int) -> float:
    return round(min(1.0, trade_count / CONFIDENCE_SATURATION_TRADES), 4)


def _insufficient_data_hypothesis(family_id: str, trade_count: int, now: str) -> Hypothesis:
    evidence = {"trade_count": trade_count, "min_required": MIN_TOTAL_TRADES}
    fingerprint = _fingerprint(family_id, "insufficient_data", evidence)
    return Hypothesis(
        family_id=family_id, pattern_type="insufficient_data",
        hypothesis_id=f"hypothesis:{family_id}:insufficient_data:{fingerprint[7:19]}",
        fingerprint=fingerprint, status=INSUFFICIENT_EVIDENCE,
        statement=(
            f"Only {trade_count} closed Paper trade(s) so far - at least {MIN_TOTAL_TRADES} are needed "
            "before any failure-pattern comparison is meaningful."
        ),
        trade_count=trade_count, confidence=None, evidence=evidence,
        expected_improvement=None,
        verification_required=("accumulate more closed Paper trades",),
        generated_at=now,
    )


def _symbol_concentration_hypothesis(family_id: str, records: Sequence[TradeRecord], now: str) -> Hypothesis | None:
    by_symbol: dict[str, float] = {}
    counted = 0
    for r in records:
        pnl = r.net_pnl if r.net_pnl is not None else r.gross_pnl
        if pnl is None:
            continue
        by_symbol[r.symbol] = by_symbol.get(r.symbol, 0.0) + pnl
        counted += 1
    total_pnl = sum(by_symbol.values())
    if counted < MIN_TOTAL_TRADES or abs(total_pnl) < 1e-9 or not by_symbol:
        evidence = {"trades_with_known_pnl": counted, "min_required": MIN_TOTAL_TRADES}
        fingerprint = _fingerprint(family_id, "symbol_concentration", evidence)
        return Hypothesis(
            family_id=family_id, pattern_type="symbol_concentration",
            hypothesis_id=f"hypothesis:{family_id}:symbol_concentration:{fingerprint[7:19]}",
            fingerprint=fingerprint, status=INSUFFICIENT_EVIDENCE,
            statement=(
                f"Only {counted} closed trade(s) with a known pnl - not enough to judge whether "
                "performance is concentrated in a small subset of symbols."
            ),
            trade_count=counted, confidence=None, evidence=evidence, expected_improvement=None,
            verification_required=("accumulate more closed Paper trades with known pnl",),
            generated_at=now,
        )
    top_symbol, top_pnl = max(by_symbol.items(), key=lambda kv: abs(kv[1]))
    share = abs(top_pnl) / abs(total_pnl)
    if share <= SYMBOL_CONCENTRATION_THRESHOLD:
        return None
    evidence = {
        "trade_count": counted, "top_symbol": top_symbol,
        "top_symbol_pnl": round(top_pnl, 6), "total_pnl": round(total_pnl, 6),
        "top_symbol_share": round(share, 4), "by_symbol_pnl": {k: round(v, 6) for k, v in by_symbol.items()},
    }
    fingerprint = _fingerprint(family_id, "symbol_concentration", evidence)
    direction = "gains" if top_pnl > 0 else "losses"
    return Hypothesis(
        family_id=family_id, pattern_type="symbol_concentration",
        hypothesis_id=f"hypothesis:{family_id}:symbol_concentration:{fingerprint[7:19]}",
        fingerprint=fingerprint, status=CANDIDATE,
        statement=(
            f"{top_symbol} alone accounts for {share:.0%} of total net PnL across {counted} closed trades "
            f"(driving {direction}) - performance may be concentrated rather than broad-based, echoing the "
            "original OOS due-diligence finding of single-symbol concentration."
        ),
        trade_count=counted, confidence=_confidence(counted), evidence=evidence,
        expected_improvement=(
            "If confirmed on more data, capping per-symbol exposure or excluding the concentrated symbol "
            "may produce a more broadly-based (less regime/symbol-dependent) edge."
        ),
        verification_required=_STANDARD_VERIFICATION_STEPS + ("re-run the OOS due-diligence concentration check against this broader forward sample",),
        generated_at=now,
    )


def _fee_drag_hypothesis(family_id: str, records: Sequence[TradeRecord], now: str) -> Hypothesis | None:
    pairs = [(r.fees, r.gross_pnl) for r in records if r.fees is not None and r.gross_pnl is not None]
    if len(pairs) < MIN_GROUP_TRADES:
        evidence = {"trades_with_known_fees_and_pnl": len(pairs), "min_required": MIN_GROUP_TRADES}
        fingerprint = _fingerprint(family_id, "fee_drag", evidence)
        return Hypothesis(
            family_id=family_id, pattern_type="fee_drag",
            hypothesis_id=f"hypothesis:{family_id}:fee_drag:{fingerprint[7:19]}",
            fingerprint=fingerprint, status=INSUFFICIENT_EVIDENCE,
            statement=(
                f"Only {len(pairs)} closed trade(s) with both fees and gross pnl known - not enough to "
                "judge whether transaction costs are materially eroding this strategy's edge."
            ),
            trade_count=len(pairs), confidence=None, evidence=evidence, expected_improvement=None,
            verification_required=("accumulate more closed Paper trades with both fees and pnl known",),
            generated_at=now,
        )
    mean_abs_fee = sum(abs(f) for f, _ in pairs) / len(pairs)
    mean_abs_gross = sum(abs(g) for _, g in pairs) / len(pairs)
    if mean_abs_gross < 1e-9:
        return None
    ratio = mean_abs_fee / mean_abs_gross
    if ratio <= FEE_DRAG_THRESHOLD:
        return None
    evidence = {
        "trade_count": len(pairs), "mean_abs_fee": round(mean_abs_fee, 6),
        "mean_abs_gross_pnl": round(mean_abs_gross, 6), "fee_to_gross_ratio": round(ratio, 4),
    }
    fingerprint = _fingerprint(family_id, "fee_drag", evidence)
    return Hypothesis(
        family_id=family_id, pattern_type="fee_drag",
        hypothesis_id=f"hypothesis:{family_id}:fee_drag:{fingerprint[7:19]}",
        fingerprint=fingerprint, status=CANDIDATE,
        statement=(
            f"Commission+funding fees average {ratio:.0%} of the mean gross PnL magnitude across "
            f"{len(pairs)} closed trades - transaction costs may be eroding this strategy's edge more "
            "than the research's own cost-model assumption accounted for."
        ),
        trade_count=len(pairs), confidence=_confidence(len(pairs)), evidence=evidence,
        expected_improvement=(
            "If confirmed on more data, tightening the liquidity filter (to avoid wider-spread symbols) "
            "or reducing rebalance frequency may reduce the cost-to-edge ratio."
        ),
        verification_required=_STANDARD_VERIFICATION_STEPS + ("recompute the historical backtest's cost-model assumption against these real observed fee rates",),
        generated_at=now,
    )


EARLY_EXIT_REASONS = ("closed_externally", "stop_loss", "take_profit")


def _early_exit_hypothesis(family_id: str, records: Sequence[TradeRecord], now: str) -> Hypothesis | None:
    scheduled = [r for r in records if r.reason == "48h_timed_exit" and r.is_win is not None]
    early = [r for r in records if r.reason in EARLY_EXIT_REASONS and r.is_win is not None]
    reason_counts = {reason: sum(1 for r in early if r.reason == reason) for reason in EARLY_EXIT_REASONS}
    total = len(scheduled) + len(early)
    if len(scheduled) < MIN_GROUP_TRADES or len(early) < MIN_GROUP_TRADES:
        evidence = {
            "scheduled_exit_trade_count": len(scheduled), "early_exit_trade_count": len(early),
            "min_required_per_group": MIN_GROUP_TRADES,
        }
        fingerprint = _fingerprint(family_id, "early_exit_vs_scheduled", evidence)
        return Hypothesis(
            family_id=family_id, pattern_type="early_exit_vs_scheduled",
            hypothesis_id=f"hypothesis:{family_id}:early_exit_vs_scheduled:{fingerprint[7:19]}",
            fingerprint=fingerprint, status=INSUFFICIENT_EVIDENCE,
            statement=(
                f"{len(scheduled)} scheduled-exit and {len(early)} early-exit trade(s) with known pnl - "
                f"at least {MIN_GROUP_TRADES} of each are needed to compare them."
            ),
            trade_count=total, confidence=None, evidence=evidence, expected_improvement=None,
            verification_required=("accumulate more closed Paper trades of both exit types",),
            generated_at=now,
        )
    scheduled_win_rate = sum(1 for r in scheduled if r.is_win) / len(scheduled)
    early_win_rate = sum(1 for r in early if r.is_win) / len(early)
    gap = scheduled_win_rate - early_win_rate
    if gap < EARLY_EXIT_WIN_RATE_GAP_THRESHOLD:
        return None
    evidence = {
        "scheduled_exit_trade_count": len(scheduled), "scheduled_exit_win_rate": round(scheduled_win_rate, 4),
        "early_exit_trade_count": len(early), "early_exit_win_rate": round(early_win_rate, 4),
        "early_exit_reason_counts": reason_counts,
        "win_rate_gap": round(gap, 4),
    }
    fingerprint = _fingerprint(family_id, "early_exit_vs_scheduled", evidence)
    return Hypothesis(
        family_id=family_id, pattern_type="early_exit_vs_scheduled",
        hypothesis_id=f"hypothesis:{family_id}:early_exit_vs_scheduled:{fingerprint[7:19]}",
        fingerprint=fingerprint, status=CANDIDATE,
        statement=(
            f"Trades closed early (before the scheduled 48h exit, e.g. by the Paper safety-net stop) win "
            f"{early_win_rate:.0%} of the time ({len(early)} trades) vs {scheduled_win_rate:.0%} for trades "
            f"that reached their scheduled exit ({len(scheduled)} trades) - a {gap:.0%} gap. The research "
            "rule itself has no stop/target by design, so frequent early stops may signal the safety-net "
            "width or entry sizing doesn't match the no-stop backtest's assumptions."
        ),
        trade_count=total, confidence=_confidence(total), evidence=evidence,
        expected_improvement=(
            "If confirmed on more data, widening (or removing) the Paper safety-net stop for this family, "
            "or reviewing entry sizing/volatility filtering, may bring live performance closer to the "
            "no-stop backtest."
        ),
        verification_required=_STANDARD_VERIFICATION_STEPS + ("historical backtest comparing the current safety-net width against no stop at all",),
        generated_at=now,
    )


def generate_hypotheses(family_id: str, records: Sequence[TradeRecord], *, now: str | None = None) -> list[Hypothesis]:
    """Deterministic, rule-based comparison of win vs loss trade
    characteristics for one family. Returns at most one hypothesis per
    pattern type considered. Below `MIN_TOTAL_TRADES` total closed trades,
    returns a single `insufficient_data` hypothesis and nothing else - no
    individual pattern is evaluated on a sample that thin."""
    now = now or datetime.now(timezone.utc).isoformat()
    trade_count = len(records)
    if trade_count < MIN_TOTAL_TRADES:
        return [_insufficient_data_hypothesis(family_id, trade_count, now)]
    hypotheses = [
        _symbol_concentration_hypothesis(family_id, records, now),
        _fee_drag_hypothesis(family_id, records, now),
        _early_exit_hypothesis(family_id, records, now),
    ]
    return [h for h in hypotheses if h is not None]
