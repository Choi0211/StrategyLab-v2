"""Patch 8.2 - Strategy Candidate: the primary unit of autonomous research.

Root cause this module fixes: production Telegram behavior showed Gaon
treating a SYMBOL (e.g. "473050") as the identity of a strategy - repeated
continuation requests kept re-researching "473050 전략" instead of
evaluating one strategy's rules across many symbols. The underlying cause
was ``gaon.research.krx_real_pipeline.CanonicalStrategySpec.fingerprint``
including ``symbol`` in its hash, so the SAME rules validated against two
different symbols produced two different "strategy identities".

This module does not reimplement backtesting, validation, or the Research
Director - it only adds the identity/bookkeeping layer that was missing:

1. ``StrategyCandidateRecord`` - a strategy's identity and accumulated
   cross-symbol/cross-cycle evidence, keyed by
   ``CanonicalStrategySpec.strategy_family_fingerprint`` (symbol-
   independent - added in Patch 8.2, see krx_real_pipeline.py).
2. A small, honest inventory of strategy "families" - see
   ``STRATEGY_FAMILY_TEMPLATES`` below for why these are named the way
   they are, not "momentum"/"mean reversion"/etc.
3. Deterministic, conservative stagnation/rotation rules so autonomous
   research moves on to a new strategy hypothesis instead of endlessly
   deep-researching one candidate (or one symbol).

Safety invariants (unchanged from Patch 8.0/8.1):
- no backtest is executed here - this module only tracks bookkeeping over
  results the existing engines already produced.
- no strategy mutation, Champion promotion, or order execution.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Mapping
from uuid import uuid4

if TYPE_CHECKING:
    from gaon.research.krx_real_pipeline import CanonicalStrategySpec

# gaon.research.krx_real_pipeline is imported LAZILY inside
# build_candidate_spec() rather than at module scope: gaon/research/__init__.py
# eagerly pulls in a long chain that ends up back at
# gaon.runtime.llm_conversation -> gaon.knowledge.research_mission -> this
# module, which would be a circular import at module-load time. Matches the
# existing deferred-import pattern used elsewhere in this package (e.g.
# gaon.knowledge.research_director_bridge).

STRATEGY_CANDIDATE_SCHEMA_VERSION = 1

# A candidate that has gone this many consecutive cycles without measurable
# progress (see record_breadth_progress/record_robustness_progress) is
# considered stagnant and should be rotated out for a new strategy
# hypothesis rather than researched indefinitely. Conservative and
# deterministic on purpose - a provider/data outage never counts toward
# this (see record_breadth_progress's provider_blocked handling).
STAGNATION_CYCLE_THRESHOLD = 3

# ULTRAREVIEW medium-issue fix: cycles_without_progress alone could in
# principle be reset indefinitely by a Research Director oscillating
# between two different actions every cycle (each change counts as
# "progress" - see record_robustness_progress). This is a hard, absolute
# ceiling on top of that: independent of any progress signal, a candidate
# that has run this many total cycles without reaching a terminal
# promotion/rejection decision is stagnant and must rotate. Generous enough
# to never cut off a genuinely converging candidate under the bounded
# per-turn execution model (one cycle per Telegram turn).
ABSOLUTE_CANDIDATE_CYCLE_CAP = 12

# A candidate needs at least this many valid symbols, AND at least this
# fraction of attempted symbols to be usable, before its cross-symbol
# evidence can support a market-wide promotion decision. "1 valid out of
# 15 attempted" must never be read as strong universe-wide evidence no
# matter how good that one symbol's result is.
MIN_VALID_SYMBOLS_FOR_UNIVERSE_EVIDENCE = 5
MIN_VALID_SYMBOL_RATIO_FOR_UNIVERSE_EVIDENCE = 0.3


class StrategyCandidateStatus(str, Enum):
    EXPLORING = "exploring"
    VALIDATING = "validating"
    ROBUSTNESS = "robustness"
    PROMOTION_READY = "promotion_ready"
    REJECTED = "rejected"
    STAGNANT = "stagnant"


@dataclass(frozen=True)
class StrategyFamilyTemplate:
    family: str
    label_ko: str
    entry: Mapping[str, object]
    exit: Mapping[str, object]
    filters: Mapping[str, object]


# Honest inventory of what the ONLY backtest engine wired into this
# codebase (gaon.research.krx_real_pipeline.RuleBasedBacktestEngine)
# actually computes: a single N-day-high BREAKOUT entry, optionally gated
# by a close>MA20 and/or MA20>MA60 trend filter and/or a volume>=MA20(20)
# filter, exited by a percentage stop-loss and/or an N-day channel low.
# There is no separate mean-reversion, momentum-continuation (without a
# breakout), or volatility-contraction computation anywhere in the engine.
#
# "Strategy family" here therefore means a distinct, named, honestly
# different COMBINATION of that engine's real tunable dimensions (trend/
# volume confirmation) - not a different algorithmic paradigm the engine
# does not implement. Naming avoids claiming "momentum"/"mean reversion"/
# "volatility contraction" as if they were separately computed.
#
# ULTRAREVIEW fix: this used to also include numeric-lookback/stop-width
# variants (breakout_fast: 10-day/-4%/7-day; breakout_wide_swing: 40-day/
# -8%/20-day). UserStrategyParser (the ONLY parser the deep single-symbol
# validation pipeline - gaon.research.krx_real_pipeline.
# RealAutonomousResearchPipeline - uses to turn request text back into a
# CanonicalStrategySpec) does not extract numbers from text at all: it only
# ever assigns the fixed literals 20/-5.0/10 regardless of what number
# appears in the text. Those two numeric-variant families could therefore
# never be deep-validated as themselves - the deep stage would silently
# validate a DIFFERENT, unrelated rule set while the candidate kept
# claiming its original (numerically distinct) fingerprint as
# "promotion-ready". Rather than rewire that deeper pipeline to accept a
# spec directly (a materially larger change, out of scope here - see
# render_candidate_request_text's docstring and
# _try_candidate_robustness_cycle's identity verification in
# llm_conversation.py for the defense-in-depth check that would catch this
# even if a future family reintroduces it), those two families are removed.
# The remaining four all use breakout_lookback=20 / protective_stop_pct=
# -5.0 / channel_exit_lookback=10 (the only values UserStrategyParser can
# ever produce) and differ only by which filters are present - every one of
# them round-trips through _FAMILY_REQUEST_TEXT -> UserStrategyParser into
# the EXACT SAME effective rule VALUES as its template (see
# tests/unit/test_strategy_candidate.py's family round-trip tests).
STRATEGY_FAMILY_TEMPLATES: tuple[StrategyFamilyTemplate, ...] = (
    StrategyFamilyTemplate(
        "breakout_standard", "표준 돌파",
        {"breakout_lookback": 20}, {"protective_stop_pct": -5.0, "channel_exit_lookback": 10}, {},
    ),
    StrategyFamilyTemplate(
        "breakout_trend_confirmed", "추세 확인 돌파 (MA20/MA60 필터)",
        {"breakout_lookback": 20, "close_gt_ma20": True, "ma20_gt_ma60": True},
        {"protective_stop_pct": -5.0, "channel_exit_lookback": 10}, {},
    ),
    StrategyFamilyTemplate(
        "breakout_volume_confirmed", "거래량 확인 돌파",
        {"breakout_lookback": 20}, {"protective_stop_pct": -5.0, "channel_exit_lookback": 10},
        {"volume_gte_ma20": True},
    ),
    StrategyFamilyTemplate(
        "breakout_multi_confirmed", "복합 확인 돌파 (추세+거래량)",
        {"breakout_lookback": 20, "close_gt_ma20": True, "ma20_gt_ma60": True},
        {"protective_stop_pct": -5.0, "channel_exit_lookback": 10}, {"volume_gte_ma20": True},
    ),
)

_TEMPLATE_BY_FAMILY = {template.family: template for template in STRATEGY_FAMILY_TEMPLATES}

# Natural-language text per family for the EXISTING single-symbol deep-
# validation pipeline (OOS/walk-forward/regime/cost/Monte Carlo via
# gaon.knowledge.telegram_autonomous_learning), which still parses its
# strategy from free text via UserStrategyParser rather than accepting a
# spec directly (unlike multi_symbol_research).
#
# ULTRAREVIEW fix: UserStrategyParser.parse triggers close_gt_ma20 on
# "ma20" OR THE BARE SUBSTRING "20일" anywhere in the text - so writing the
# breakout day-count as "20일" (the natural Korean phrasing) silently
# turned on the MA20 trend filter on every family, including ones that
# never asked for it, which then failed to match their own candidate's
# fingerprint. The day-count below is written as "20" (no "일" suffix) so
# it satisfies the breakout_lookback trigger (needs "20" plus 고가/돌파)
# without also satisfying the unrelated close_gt_ma20 trigger; "MA20"/
# "MA60" appear ONLY in the two families that actually want that filter.
# Every family's text below has been verified (see
# tests/unit/test_strategy_candidate.py) to parse into EXACTLY its
# template's entry/exit/filters - no more, no less.
_FAMILY_REQUEST_TEXT: Mapping[str, str] = {
    "breakout_standard": "20 고가 돌파 손절 -5% 10일 저점 이탈 청산",
    "breakout_trend_confirmed": "20 고가 돌파 종가 > MA20 > MA60 손절 -5% 10일 저점 이탈 청산",
    "breakout_volume_confirmed": "20 고가 돌파 거래량 평균 이상 손절 -5% 10일 저점 이탈 청산",
    "breakout_multi_confirmed": "20 고가 돌파 종가 > MA20 > MA60 거래량 평균 이상 손절 -5% 10일 저점 이탈 청산",
}


def render_candidate_request_text(candidate: "StrategyCandidateRecord", symbol: str) -> str:
    """Builds the request text for a deep single-symbol robustness cycle
    validating ``candidate`` using ``symbol`` as the evaluation sample.

    Deliberately a clean, human-readable research request (safe to forward
    to external research providers verbatim, like any other request text
    this pipeline already sends externally) - never embeds internal
    control metadata (candidate_id, mission_id, cycle counters). Candidate
    attribution is done separately by the caller, from the returned
    strategy's own rules - not by parsing this text back."""
    base = _FAMILY_REQUEST_TEXT.get(candidate.strategy_family, _FAMILY_REQUEST_TEXT["breakout_standard"])
    return f"{symbol} {base}"


def _template(family: str) -> StrategyFamilyTemplate:
    try:
        return _TEMPLATE_BY_FAMILY[family]
    except KeyError as exc:
        raise ValueError(f"unknown strategy family: {family}") from exc


def build_candidate_spec(family: str, *, placeholder_symbol: str = "005930", created_at: str) -> "CanonicalStrategySpec":
    """Constructs a CanonicalStrategySpec directly from a family template,
    bypassing free-text parsing (UserStrategyParser can only reliably
    reproduce a narrow subset of parameter values from natural language).
    ``placeholder_symbol`` never affects identity - see
    ``CanonicalStrategySpec.strategy_family_fingerprint``."""
    from gaon.research.krx_real_pipeline import CanonicalStrategySpec, FieldProvenance, ProvenancedValue

    template = _template(family)
    entry = {key: ProvenancedValue(value, FieldProvenance.RESEARCH_CANDIDATE) for key, value in template.entry.items()}
    exit_rules = {key: ProvenancedValue(value, FieldProvenance.RESEARCH_CANDIDATE) for key, value in template.exit.items()}
    filters = {key: ProvenancedValue(value, FieldProvenance.RESEARCH_CANDIDATE) for key, value in template.filters.items()}
    return CanonicalStrategySpec(
        spec_id=f"strategy-family:{family}:{uuid4().hex[:8]}",
        symbol=placeholder_symbol.upper(),
        entry=entry,
        exit=exit_rules,
        filters=filters,
        source_text=f"strategy-family-template:{family}",
        created_at=created_at,
    )


def spec_rules_to_json(spec: CanonicalStrategySpec) -> dict[str, object]:
    """JSON-safe encoding of a spec's RULES ONLY (entry/exit/filters) -
    what ``multi_symbol_research``'s ``candidate_spec`` tool argument
    carries, and what ``candidate_spec_from_rules_json`` (in
    ``gaon.research.multi_symbol``) reconstructs an equivalent spec from.
    Never includes symbol/spec_id/timestamps - those are per-evaluation,
    not part of the strategy's identity."""
    return {
        "entry": {key: value.to_json() for key, value in sorted(spec.entry.items())},
        "exit": {key: value.to_json() for key, value in sorted(spec.exit.items())},
        "filters": {key: value.to_json() for key, value in sorted(spec.filters.items())},
    }


def next_untried_family(existing: tuple["StrategyCandidateRecord", ...]) -> str | None:
    """Picks the next strategy family not yet represented by any candidate
    in ``existing``, in template order - diversity across supported
    families before any local parameter mutation, per Patch 8.2's research
    diversity requirement. Returns None once every template has been
    tried at least once (callers may then choose to stop generating new
    candidates within this mission, or fall back to local mutation of the
    most promising family - not implemented here to keep this module's
    surface small; see the completion report)."""
    used = {candidate.strategy_family for candidate in existing}
    for template in STRATEGY_FAMILY_TEMPLATES:
        if template.family not in used:
            return template.family
    return None


@dataclass(frozen=True)
class StrategyCandidateRecord:
    candidate_id: str
    strategy_fingerprint: str
    strategy_family: str
    spec_rules: Mapping[str, object]
    hypothesis_summary: str
    parent_candidate_id: str | None
    generation: int
    status: StrategyCandidateStatus
    attempted_symbols: int
    valid_symbols: int
    trade_count: int
    evidence_symbols: tuple[str, ...]
    excluded_symbols: tuple[str, ...]
    cycles_completed: int
    cycles_without_progress: int
    last_director_action: str | None
    rejected_reason: str | None
    promotion_ready_at: str | None
    created_at: str
    updated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": STRATEGY_CANDIDATE_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "strategy_fingerprint": self.strategy_fingerprint,
            "strategy_family": self.strategy_family,
            "spec_rules": dict(self.spec_rules),
            "hypothesis_summary": self.hypothesis_summary,
            "parent_candidate_id": self.parent_candidate_id,
            "generation": self.generation,
            "status": self.status.value,
            "attempted_symbols": self.attempted_symbols,
            "valid_symbols": self.valid_symbols,
            "trade_count": self.trade_count,
            "evidence_symbols": list(self.evidence_symbols),
            "excluded_symbols": list(self.excluded_symbols),
            "cycles_completed": self.cycles_completed,
            "cycles_without_progress": self.cycles_without_progress,
            "last_director_action": self.last_director_action,
            "rejected_reason": self.rejected_reason,
            "promotion_ready_at": self.promotion_ready_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_json(raw: Mapping[str, object]) -> "StrategyCandidateRecord":
        return StrategyCandidateRecord(
            candidate_id=str(raw["candidate_id"]),
            strategy_fingerprint=str(raw["strategy_fingerprint"]),
            strategy_family=str(raw["strategy_family"]),
            spec_rules=dict(raw.get("spec_rules") or {}),
            hypothesis_summary=str(raw.get("hypothesis_summary", "")),
            parent_candidate_id=str(raw["parent_candidate_id"]) if raw.get("parent_candidate_id") else None,
            generation=int(raw.get("generation", 0) or 0),
            status=StrategyCandidateStatus(str(raw.get("status", StrategyCandidateStatus.EXPLORING.value))),
            attempted_symbols=int(raw.get("attempted_symbols", 0) or 0),
            valid_symbols=int(raw.get("valid_symbols", 0) or 0),
            trade_count=int(raw.get("trade_count", 0) or 0),
            evidence_symbols=tuple(str(item) for item in raw.get("evidence_symbols", ()) or ()),
            excluded_symbols=tuple(str(item) for item in raw.get("excluded_symbols", ()) or ()),
            cycles_completed=int(raw.get("cycles_completed", 0) or 0),
            cycles_without_progress=int(raw.get("cycles_without_progress", 0) or 0),
            last_director_action=str(raw["last_director_action"]) if raw.get("last_director_action") else None,
            rejected_reason=str(raw["rejected_reason"]) if raw.get("rejected_reason") else None,
            promotion_ready_at=str(raw["promotion_ready_at"]) if raw.get("promotion_ready_at") else None,
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
        )

    @property
    def valid_symbol_ratio(self) -> float | None:
        if self.attempted_symbols <= 0:
            return None
        return self.valid_symbols / self.attempted_symbols

    @property
    def has_sufficient_universe_evidence(self) -> bool:
        ratio = self.valid_symbol_ratio
        if ratio is None:
            return False
        return (
            self.valid_symbols >= MIN_VALID_SYMBOLS_FOR_UNIVERSE_EVIDENCE
            and ratio >= MIN_VALID_SYMBOL_RATIO_FOR_UNIVERSE_EVIDENCE
        )


def new_candidate(
    family: str,
    *,
    sequence: int,
    now: str,
    parent_candidate_id: str | None = None,
    generation: int = 0,
) -> StrategyCandidateRecord:
    spec = build_candidate_spec(family, created_at=now)
    template = _template(family)
    return StrategyCandidateRecord(
        candidate_id=f"KR-ST-{sequence:03d}",
        strategy_fingerprint=spec.strategy_family_fingerprint,
        strategy_family=family,
        spec_rules=spec_rules_to_json(spec),
        hypothesis_summary=template.label_ko,
        parent_candidate_id=parent_candidate_id,
        generation=generation,
        status=StrategyCandidateStatus.EXPLORING,
        attempted_symbols=0,
        valid_symbols=0,
        trade_count=0,
        evidence_symbols=(),
        excluded_symbols=(),
        cycles_completed=0,
        cycles_without_progress=0,
        last_director_action=None,
        rejected_reason=None,
        promotion_ready_at=None,
        created_at=now,
        updated_at=now,
    )


def record_breadth_progress(
    candidate: StrategyCandidateRecord,
    *,
    attempted: int,
    valid: int,
    trade_count: int,
    evidence_symbols: tuple[str, ...],
    excluded_symbols: tuple[str, ...],
    provider_blocked: bool,
    now: str,
) -> StrategyCandidateRecord:
    """Records one cross-symbol (breadth) evaluation cycle's outcome.

    A provider/data-acquisition-blocked cycle (see
    ``gaon.knowledge.research_mission.is_provider_acquisition_blocker``)
    never counts toward stagnation - a strategy is never penalized for a
    data outage.
    """
    progressed = valid > candidate.valid_symbols or trade_count > candidate.trade_count
    if progressed:
        cycles_without_progress = 0
    elif provider_blocked:
        cycles_without_progress = candidate.cycles_without_progress
    else:
        cycles_without_progress = candidate.cycles_without_progress + 1
    status = candidate.status
    if status is StrategyCandidateStatus.EXPLORING:
        status = StrategyCandidateStatus.VALIDATING
    return replace(
        candidate,
        attempted_symbols=attempted,
        valid_symbols=valid,
        trade_count=trade_count,
        evidence_symbols=tuple(dict.fromkeys((*candidate.evidence_symbols, *evidence_symbols)))[:8],
        excluded_symbols=tuple(dict.fromkeys((*candidate.excluded_symbols, *excluded_symbols)))[:8],
        cycles_completed=candidate.cycles_completed + 1,
        cycles_without_progress=cycles_without_progress,
        status=status,
        updated_at=now,
    )


def record_robustness_progress(
    candidate: StrategyCandidateRecord,
    *,
    director_action: str,
    terminal: bool,
    now: str,
) -> StrategyCandidateRecord:
    """Records one deep (single-symbol-anchored OOS/walk-forward/regime/
    cost/Monte Carlo) robustness cycle's outcome - the symbol used to run
    this cycle is evidence FOR this candidate, not a new identity; callers
    are responsible for choosing that symbol from the candidate's own
    validated evidence set."""
    progressed = director_action != candidate.last_director_action
    cycles_without_progress = 0 if progressed else candidate.cycles_without_progress + 1
    status = candidate.status if terminal else StrategyCandidateStatus.ROBUSTNESS
    return replace(
        candidate,
        last_director_action=director_action,
        cycles_completed=candidate.cycles_completed + 1,
        cycles_without_progress=cycles_without_progress,
        status=status,
        updated_at=now,
    )


def is_stagnant(candidate: StrategyCandidateRecord) -> bool:
    if candidate.status in (StrategyCandidateStatus.PROMOTION_READY, StrategyCandidateStatus.REJECTED, StrategyCandidateStatus.STAGNANT):
        return False
    if candidate.cycles_completed >= ABSOLUTE_CANDIDATE_CYCLE_CAP:
        return True
    return candidate.cycles_without_progress >= STAGNATION_CYCLE_THRESHOLD


def mark_promotion_ready(candidate: StrategyCandidateRecord, *, now: str) -> StrategyCandidateRecord:
    return replace(candidate, status=StrategyCandidateStatus.PROMOTION_READY, promotion_ready_at=now, updated_at=now)


def mark_rejected(candidate: StrategyCandidateRecord, *, reason: str, now: str) -> StrategyCandidateRecord:
    return replace(candidate, status=StrategyCandidateStatus.REJECTED, rejected_reason=reason, updated_at=now)


def mark_stagnant(
    candidate: StrategyCandidateRecord,
    *,
    now: str,
    reason: str = "stagnation: no measurable progress across bounded cycles",
) -> StrategyCandidateRecord:
    return replace(candidate, status=StrategyCandidateStatus.STAGNANT, rejected_reason=reason, updated_at=now)


_STATUS_LABELS_KO: Mapping[StrategyCandidateStatus, str] = {
    StrategyCandidateStatus.EXPLORING: "탐색 시작",
    StrategyCandidateStatus.VALIDATING: "다종목 검증 중",
    StrategyCandidateStatus.ROBUSTNESS: "정밀 검증 중",
    StrategyCandidateStatus.PROMOTION_READY: "승격 준비 완료",
    StrategyCandidateStatus.REJECTED: "기각",
    StrategyCandidateStatus.STAGNANT: "정체(다른 전략으로 전환)",
}


def render_candidate_block(candidate: StrategyCandidateRecord) -> str:
    lines = [
        f"[전략 후보 {candidate.candidate_id}]",
        f"전략: {candidate.hypothesis_summary}",
    ]
    if candidate.attempted_symbols:
        lines.append(f"검증 표본: 유효 {candidate.valid_symbols}종목 / 시도 {candidate.attempted_symbols}종목")
    if candidate.trade_count:
        lines.append(f"거래 표본: {candidate.trade_count}건")
    lines.append(f"상태: {_STATUS_LABELS_KO.get(candidate.status, candidate.status.value)}")
    if candidate.last_director_action:
        lines.append(f"최근 검증 단계: {candidate.last_director_action}")
    return "\n".join(lines)


def render_candidate_status_summary(candidates: tuple[StrategyCandidateRecord, ...], *, current: int, target: int | None) -> str:
    active = [candidate for candidate in candidates if candidate.status in (StrategyCandidateStatus.EXPLORING, StrategyCandidateStatus.VALIDATING, StrategyCandidateStatus.ROBUSTNESS)]
    if not active:
        target_label = str(target) if target is not None else "미지정"
        return f"영하님, 현재 검증 중인 전략 후보가 없습니다. 승격 준비 후보는 현재 {current}/{target_label}입니다."
    names = ", ".join(candidate.candidate_id for candidate in active)
    lines = [f"영하님, 현재 {names} {'전략 후보를' if len(active) > 1 else '전략 후보를'} 검증 중입니다."]
    for candidate in active:
        lines.append(f"- {candidate.candidate_id}({candidate.hypothesis_summary}): {_STATUS_LABELS_KO.get(candidate.status, candidate.status.value)}, 유효 {candidate.valid_symbols}/{candidate.attempted_symbols}종목")
    target_label = str(target) if target is not None else "미지정"
    lines.append(f"승격 준비 후보는 현재 {current}/{target_label}입니다.")
    return "\n".join(lines)
