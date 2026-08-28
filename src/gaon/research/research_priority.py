"""Read-only, evidence-based research priority proposal across the KR
ResearchMission and Binance's own read-only research summary (Hotfix #166,
Section 6: Proactive Research Prioritization).

Boundary this module deliberately preserves: it never mutates anything, and
it never triggers or influences autonomous research on Binance -
``gaon.adapters.binance`` has zero order-execution or write capability at
all (see that module's own docstring), and this module only ever calls its
read-only reader methods (``BinanceResearchReader.family_summary``). It
also never invents a "profit is low, so do something risky" verdict: every
KR-side flag reuses the exact same real, already-persisted read models
(``ResearchMission.status``, ``candidate_remaining_blockers``) the mission-
driven research cycle itself already computes; every Binance-side flag
reuses the exact same real, already-computed OOS walk-forward summary
``gaon.adapters.binance`` already exposes for the champion/challenger
comparison path. No fabricated threshold or invented scoring formula is
used to force a single winner - this function surfaces which domain(s)
have a REAL, structurally-identified reason to be prioritized (a blocked
mission, an unresolved candidate blocker, missing/insufficient Binance
research data) as a proposal a human/operator can act on, never an
automatic switch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gaon.adapters.binance import BinanceAdapterConfig, BinanceResearchFamilySummary, BinanceResearchReader
from gaon.knowledge.research_mission import MissionStatus, ResearchMission, get_active_candidate
from gaon.knowledge.strategy_candidate import candidate_remaining_blockers


@dataclass(frozen=True)
class DomainResearchEvidence:
    domain: str
    available: bool
    flags: tuple[str, ...]
    evidence: dict[str, object]

    def to_json(self) -> dict[str, object]:
        return {"domain": self.domain, "available": self.available, "flags": list(self.flags), "evidence": self.evidence}


@dataclass(frozen=True)
class ResearchPriorityProposal:
    kr: DomainResearchEvidence
    binance: DomainResearchEvidence
    flagged_domains: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, object]:
        return {
            "kr": self.kr.to_json(),
            "binance": self.binance.to_json(),
            "flagged_domains": list(self.flagged_domains),
            "note": "read-only proposal; no automatic action taken in either domain",
        }


def _kr_evidence(mission: ResearchMission | None) -> DomainResearchEvidence:
    if mission is None:
        return DomainResearchEvidence("kr", False, ("no_active_mission",), {})
    flags: list[str] = []
    active = get_active_candidate(mission)
    evidence: dict[str, object] = {
        "mission_status": mission.status.value,
        "progress_label": mission.progress_label,
        "active_candidate_id": mission.active_candidate_id,
    }
    if mission.status is MissionStatus.BLOCKED:
        flags.append("blocked")
        evidence["blocked_reason"] = mission.blocked_reason
    if active is not None:
        remaining = candidate_remaining_blockers(active)
        evidence["active_candidate_remaining_blockers"] = list(remaining)
        if remaining:
            flags.append("active_candidate_has_unresolved_blockers")
    return DomainResearchEvidence("kr", True, tuple(flags), evidence)


def _binance_evidence(config: BinanceAdapterConfig | None, *, family_id: str) -> DomainResearchEvidence:
    if config is None:
        return DomainResearchEvidence("binance", False, ("not_configured",), {})
    summary: BinanceResearchFamilySummary | None
    try:
        summary = BinanceResearchReader(config).family_summary(family_id)
    except (OSError, ValueError):
        return DomainResearchEvidence("binance", False, ("read_error",), {})
    if summary is None:
        return DomainResearchEvidence("binance", False, ("no_research_data", f"family_not_found:{family_id}"), {})
    flags: list[str] = []
    if summary.num_folds == 0 or summary.oos_total_trades == 0:
        flags.append("insufficient_sample")
    return DomainResearchEvidence(
        "binance",
        True,
        tuple(flags),
        {
            "family_id": summary.family_id,
            "num_folds": summary.num_folds,
            "oos_total_trades": summary.oos_total_trades,
            "oos_win_rate": summary.oos_win_rate,
            "oos_mean_return_pct": summary.oos_mean_return_pct,
            "oos_max_drawdown_pct": summary.oos_max_drawdown_pct,
            "oos_profitable_symbol_ratio": summary.oos_profitable_symbol_ratio,
        },
    )


def propose_research_priority(
    mission: ResearchMission | None,
    binance_config: BinanceAdapterConfig | None,
    *,
    binance_family_id: str = "price_action",
) -> ResearchPriorityProposal:
    """Builds a read-only, evidence-grounded research-priority proposal.

    Never raises for missing/unavailable data on either side - an
    unconfigured or empty Binance research directory is reported as an
    honest ``not_configured``/``no_research_data`` flag, never silently
    substituted with fixture/synthetic data.
    """
    kr = _kr_evidence(mission)
    binance = _binance_evidence(binance_config, family_id=binance_family_id)
    flagged = tuple(domain.domain for domain in (kr, binance) if domain.flags)
    return ResearchPriorityProposal(kr=kr, binance=binance, flagged_domains=flagged)
