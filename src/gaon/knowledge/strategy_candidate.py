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

from dataclasses import dataclass, field, replace
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
# principle be reset indefinitely by spurious non-evidence changes. This is
# a hard, absolute ceiling on top of that: independent of any progress
# signal, a candidate that has run this many total cycles without reaching a terminal
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

# Patch 8.6: bounded rotation memory of symbols already used as a ROBUSTNESS
# (deep single-symbol OOS/walk-forward/regime/cost/Monte Carlo) evaluation
# sample under one candidate's fingerprint - same cap as breadth's
# evidence_symbols (see record_breadth_progress) for consistency.
BREADTH_EVIDENCE_SYMBOL_CAP = 64
ROBUSTNESS_EVIDENCE_SYMBOL_CAP = BREADTH_EVIDENCE_SYMBOL_CAP
PROMOTION_MIN_TRADE_SAMPLE = 30

PASS_LIKE_STAGE_STATUSES = frozenset(
    {
        "pass",
        "stable",
        "cost_stable",
        "acceptable",
        "sufficient",
    }
)

ACTION_STAGE_KEYS = {
    "RUN_OOS": "out_of_sample",
    "RUN_REGIME": "regime_validation",
    "RUN_WALK_FORWARD": "walk_forward",
    "RUN_COST_STRESS": "transaction_cost_stress",
    "RUN_SENSITIVITY": "parameter_sensitivity",
    "RUN_MONTE_CARLO": "monte_carlo",
}
ACTION_CYCLE_HISTORY_CAP = 48

# Root cause this closes: KR-ST-008 (production, 2026-08) kept receiving
# EXPAND_SYMBOLS/EXPAND_SAMPLE forever - 5/41 -> 10/75 -> 15/112 -> 20/149
# symbols/trades - while its own batch reports showed consistently negative
# median returns (-20.2%, -23.0%, +1.4%, -7.8%) and large drawdowns (35-47%
# MDD). candidate_remaining_blockers()/next_blocker_driven_research_action()
# below only ever gated on WHETHER a validation stage ran (OOS/walk-forward/
# regime/cost/Monte Carlo "PASS"), never on WHETHER the strategy actually
# made money. A candidate whose robustness stages kept coming back partial
# was therefore never rejected - "not yet passing" always reset
# cycles_without_progress via new breadth evidence, so EXPAND_SAMPLE could
# run until the entire candidate symbol pool was exhausted, no matter how
# decisively unprofitable the accumulating evidence was. See
# evaluate_economic_viability() below - an ABSOLUTE (not relative-to-
# baseline) profitability/risk gate, deliberately separate from robustness.
#
# The sample-size bar for an economic (accept/reject) verdict is
# intentionally set well above MIN_VALID_SYMBOLS_FOR_UNIVERSE_EVIDENCE/
# PROMOTION_MIN_TRADE_SAMPLE (which only gate "enough to start validating at
# all"): a 5-symbol/41-trade batch is real evidence but not enough to
# conclude a strategy is a structural loser rather than an unlucky sample -
# see KR-ST-008's own batch-to-batch swing (-20.2% -> +1.4% -> -7.8%). These
# thresholds are an explicit, bounded, project-owned policy (see
# EconomicViabilityPolicy) - not a fabricated "X% return is good" number:
# the pass/fail boundary itself is anchored at zero return / a bare-majority
# profitable-symbol ratio, never an invented magnitude.
ECONOMIC_VIABILITY_MIN_SYMBOL_SAMPLE = 20
ECONOMIC_VIABILITY_MIN_TRADE_SAMPLE = 120
ECONOMIC_VIABILITY_MIN_PROFITABLE_SYMBOL_RATIO = 0.5

class StrategyCandidateStatus(str, Enum):
    EXPLORING = "exploring"
    VALIDATING = "validating"
    ROBUSTNESS = "robustness"
    PROMOTION_READY = "promotion_ready"
    REJECTED = "rejected"
    STAGNANT = "stagnant"


class EconomicViabilityStatus(str, Enum):
    """Absolute (not relative-to-baseline) profitability/risk verdict over a
    candidate's own CANONICAL cumulative performance evidence - deliberately
    separate from robustness (OOS/walk-forward/regime/cost/Monte Carlo)
    completion. Robustness PASS answers "is this measured honestly"; this
    answers "is what was honestly measured actually worth trading"."""

    PASS = "pass"
    FAIL = "fail"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


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

# Strategy-space expansion templates. These are deliberately outside
# STRATEGY_FAMILY_TEMPLATES so the historical "base family space exhausted"
# state remains observable. They still use only the existing
# RuleBasedBacktestEngine grammar: breakout lookback, trend/volume filters,
# channel-low exits, and percentage stops.
STRATEGY_SPACE_EXPANSION_TEMPLATES: tuple[StrategyFamilyTemplate, ...] = (
    StrategyFamilyTemplate(
        "breakout_fast_volume_confirmed", "빠른 거래량 확인 돌파",
        {"breakout_lookback": 10}, {"protective_stop_pct": -4.0, "channel_exit_lookback": 7},
        {"volume_gte_ma20": True},
    ),
    StrategyFamilyTemplate(
        "breakout_slow_trend_confirmed", "느린 추세 확인 돌파",
        {"breakout_lookback": 30, "close_gt_ma20": True, "ma20_gt_ma60": True},
        {"protective_stop_pct": -5.0, "channel_exit_lookback": 15}, {},
    ),
    StrategyFamilyTemplate(
        "breakout_slow_multi_confirmed", "느린 복합 확인 돌파",
        {"breakout_lookback": 30, "close_gt_ma20": True, "ma20_gt_ma60": True},
        {"protective_stop_pct": -6.0, "channel_exit_lookback": 15}, {"volume_gte_ma20": True},
    ),
    StrategyFamilyTemplate(
        "breakout_wide_standard", "넓은 채널 돌파",
        {"breakout_lookback": 40}, {"protective_stop_pct": -8.0, "channel_exit_lookback": 20}, {},
    ),
    StrategyFamilyTemplate(
        "breakout_fast_trend_confirmed", "빠른 추세 확인 돌파",
        {"breakout_lookback": 10, "close_gt_ma20": True, "ma20_gt_ma60": True},
        {"protective_stop_pct": -4.0, "channel_exit_lookback": 7}, {},
    ),
)

ALL_STRATEGY_FAMILY_TEMPLATES = (*STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_TEMPLATES)

_TEMPLATE_BY_FAMILY = {template.family: template for template in ALL_STRATEGY_FAMILY_TEMPLATES}

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
    "breakout_fast_volume_confirmed": "10 고가 돌파 거래량 평균 이상 손절 -4% 7일 저점 이탈 청산",
    "breakout_slow_trend_confirmed": "30 고가 돌파 종가 > MA20 > MA60 손절 -5% 15일 저점 이탈 청산",
    "breakout_slow_multi_confirmed": "30 고가 돌파 종가 > MA20 > MA60 거래량 평균 이상 손절 -6% 15일 저점 이탈 청산",
    "breakout_wide_standard": "40 고가 돌파 손절 -8% 20일 저점 이탈 청산",
    "breakout_fast_trend_confirmed": "10 고가 돌파 종가 > MA20 > MA60 손절 -4% 7일 저점 이탈 청산",
}


@dataclass(frozen=True)
class StrategySpaceExpansion:
    action: str
    reason: str
    candidate: "StrategyCandidateRecord | None"
    evidence_signals: tuple[str, ...]
    skipped_fingerprints: tuple[str, ...]
    search_budget: int

    def to_json(self) -> dict[str, object]:
        return {
            "action": self.action,
            "reason": self.reason,
            "candidate_id": self.candidate.candidate_id if self.candidate else None,
            "strategy_family": self.candidate.strategy_family if self.candidate else None,
            "strategy_fingerprint": self.candidate.strategy_fingerprint if self.candidate else None,
            "evidence_signals": list(self.evidence_signals),
            "skipped_fingerprints": list(self.skipped_fingerprints),
            "search_budget": self.search_budget,
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


def expand_strategy_space_candidate(
    existing: tuple["StrategyCandidateRecord", ...],
    *,
    sequence: int,
    now: str,
) -> StrategySpaceExpansion:
    """Generates the next bounded, evidence-linked strategy hypothesis.

    This is the explicit continuation path once the base family inventory is
    exhausted. It never fabricates performance. It only reads persisted
    candidate blockers/status, picks from the bounded declarative grammar
    above, rejects semantic duplicates by strategy fingerprint, and returns a
    normal StrategyCandidateRecord for the existing mission pipeline to
    validate through multi_symbol_research.
    """
    evidence_signals = _mission_failure_signals(existing)
    known_fingerprints = {candidate.strategy_fingerprint for candidate in existing}
    used_families = {candidate.strategy_family for candidate in existing}
    skipped: list[str] = []
    ranked = _rank_expansion_templates(evidence_signals)
    for template in ranked[: len(STRATEGY_SPACE_EXPANSION_TEMPLATES)]:
        spec = build_candidate_spec(template.family, created_at=now)
        fingerprint = spec.strategy_family_fingerprint
        if template.family in used_families or fingerprint in known_fingerprints:
            skipped.append(fingerprint)
            continue
        candidate = new_candidate(template.family, sequence=sequence, now=now)
        return StrategySpaceExpansion(
            action="EXPAND_STRATEGY_SPACE",
            reason="strategy_family_space_exhausted",
            candidate=candidate,
            evidence_signals=evidence_signals,
            skipped_fingerprints=tuple(skipped),
            search_budget=len(STRATEGY_SPACE_EXPANSION_TEMPLATES),
        )
    return StrategySpaceExpansion(
        action="EXPAND_STRATEGY_SPACE",
        reason="strategy_hypothesis_space_exhausted",
        candidate=None,
        evidence_signals=evidence_signals,
        skipped_fingerprints=tuple(skipped),
        search_budget=len(STRATEGY_SPACE_EXPANSION_TEMPLATES),
    )


def _mission_failure_signals(existing: tuple["StrategyCandidateRecord", ...]) -> tuple[str, ...]:
    signals: list[str] = []
    for candidate in existing:
        if candidate.status in (StrategyCandidateStatus.STAGNANT, StrategyCandidateStatus.REJECTED):
            signals.append(f"candidate_{candidate.status.value}")
        if candidate.rejected_reason:
            signals.append(candidate.rejected_reason)
        if candidate.trade_count < PROMOTION_MIN_TRADE_SAMPLE:
            signals.append("insufficient_trade_sample")
        if candidate.attempted_symbols and not candidate.has_sufficient_universe_evidence:
            signals.append("cross_symbol_weakness")
        for blocker in candidate_remaining_blockers(candidate):
            signals.append(blocker)
        for stage, status in sorted(candidate.validation_stage_status.items()):
            if status not in PASS_LIKE_STAGE_STATUSES:
                signals.append(f"{stage}_{status}")
    return tuple(dict.fromkeys(signals)) or ("base_family_space_exhausted",)


def _rank_expansion_templates(evidence_signals: tuple[str, ...]) -> tuple[StrategyFamilyTemplate, ...]:
    signal_text = " ".join(evidence_signals)

    def score(template: StrategyFamilyTemplate) -> tuple[int, str]:
        value = 0
        lookback = int(template.entry.get("breakout_lookback", 20))
        has_trend = bool(template.entry.get("close_gt_ma20") or template.entry.get("ma20_gt_ma60"))
        has_volume = bool(template.filters.get("volume_gte_ma20"))
        stop = abs(float(template.exit.get("protective_stop_pct", -5.0)))
        if "insufficient_trade_sample" in signal_text or "minimum_trade_sample" in signal_text:
            value += 4 if lookback <= 10 else 0
        if "transaction_cost_stress" in signal_text or "cost_fragile" in signal_text:
            value += 3 if lookback >= 30 else 0
            value += 1 if has_trend else 0
        if "regime_validation" in signal_text or "walk_forward" in signal_text or "out_of_sample" in signal_text:
            value += 2 if has_trend else 0
            value += 1 if has_volume else 0
        if "cross_symbol_weakness" in signal_text or "multi_symbol" in signal_text:
            value += 2 if has_volume else 0
        if stop >= 8.0 and ("parameter_sensitivity" in signal_text or "mdd" in signal_text):
            value += 1
        return (-value, template.family)

    return tuple(sorted(STRATEGY_SPACE_EXPANSION_TEMPLATES, key=score))


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
    # Patch 8.5: honest, per-stage deep-validation status, read verbatim
    # from the EXISTING Autonomous Learning V2 / Research Director
    # production_grade_validation output (see
    # gaon.runtime.llm_conversation._try_candidate_robustness_cycle) -
    # never fabricated. A key absent from this mapping (or the whole
    # mapping being empty, e.g. for a candidate that has never entered
    # robustness validation) must be rendered as "not_run"/"unavailable",
    # never guessed as pass/fail.
    validation_stage_status: Mapping[str, str] = field(default_factory=dict)
    # Patch 8.6: cross-symbol ROBUSTNESS evidence tracking - distinct from
    # evidence_symbols (breadth's cross-symbol validation pool, the SOURCE
    # this rotates through). Real production defect this closes: the deep
    # single-symbol validation pipeline only ever deepened ONE symbol via
    # cross-turn steps_used, with no memory of which symbols had already
    # been used as a robustness sample - a market-wide mission could never
    # actually validate the same strategy fingerprint against multiple
    # symbols at the robustness stage. See next_robustness_evidence_symbol
    # and gaon.runtime.llm_conversation._try_candidate_robustness_cycle.
    robustness_evidence_symbols: tuple[str, ...] = field(default_factory=tuple)
    robustness_attempt_count: int = 0
    last_validation_symbol: str | None = None
    last_validation_reference: str | None = None
    # Canonical breadth evidence keyed by symbol. The legacy scalar fields
    # above (attempted_symbols, valid_symbols, trade_count, evidence_symbols,
    # excluded_symbols) are derived from this map for new records. Older
    # production records that predate this field keep their already persisted
    # aggregate trade count as a floor in breadth_legacy_trade_count so a
    # restart cannot regress 10-symbol evidence back to a 5-symbol batch.
    breadth_evidence: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    breadth_legacy_trade_count: int = 0
    sample_exhaustion_reason: str | None = None
    breadth_summary: Mapping[str, object] = field(default_factory=dict)
    validation_attempt_history: tuple[Mapping[str, object], ...] = field(default_factory=tuple)

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
            "validation_stage_status": dict(self.validation_stage_status),
            "robustness_evidence_symbols": list(self.robustness_evidence_symbols),
            "robustness_attempt_count": self.robustness_attempt_count,
            "last_validation_symbol": self.last_validation_symbol,
            "last_validation_reference": self.last_validation_reference,
            "breadth_evidence": {str(key): dict(value) for key, value in self.breadth_evidence.items()},
            "breadth_legacy_trade_count": self.breadth_legacy_trade_count,
            "sample_exhaustion_reason": self.sample_exhaustion_reason,
            "breadth_summary": dict(self.breadth_summary),
            "validation_attempt_history": [dict(item) for item in self.validation_attempt_history],
        }

    @staticmethod
    def from_json(raw: Mapping[str, object]) -> "StrategyCandidateRecord":
        breadth_evidence_raw = raw.get("breadth_evidence")
        if isinstance(breadth_evidence_raw, Mapping):
            breadth_evidence = {
                str(key): dict(value) for key, value in dict(breadth_evidence_raw).items() if isinstance(value, Mapping)
            }
            breadth_legacy_trade_count = int(raw.get("breadth_legacy_trade_count", 0) or 0)
        else:
            breadth_evidence = {}
            for symbol in raw.get("evidence_symbols", ()) or ():
                breadth_evidence[str(symbol)] = {"symbol": str(symbol), "eligible": True, "trade_count": 0, "source": "legacy_candidate_state"}
            for symbol in raw.get("excluded_symbols", ()) or ():
                breadth_evidence.setdefault(
                    str(symbol),
                    {"symbol": str(symbol), "eligible": False, "trade_count": 0, "source": "legacy_candidate_state"},
                )
            breadth_legacy_trade_count = int(raw.get("trade_count", 0) or 0) if breadth_evidence else 0
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
            validation_stage_status={
                str(key): str(value) for key, value in dict(raw.get("validation_stage_status") or {}).items()
            },
            robustness_evidence_symbols=tuple(str(item) for item in raw.get("robustness_evidence_symbols", ()) or ()),
            robustness_attempt_count=int(raw.get("robustness_attempt_count", 0) or 0),
            last_validation_symbol=str(raw["last_validation_symbol"]) if raw.get("last_validation_symbol") else None,
            last_validation_reference=str(raw["last_validation_reference"]) if raw.get("last_validation_reference") else None,
            breadth_evidence=breadth_evidence,
            breadth_legacy_trade_count=breadth_legacy_trade_count,
            sample_exhaustion_reason=str(raw["sample_exhaustion_reason"]) if raw.get("sample_exhaustion_reason") else None,
            breadth_summary=dict(raw.get("breadth_summary") or {}),
            validation_attempt_history=tuple(
                dict(item) for item in raw.get("validation_attempt_history", ()) or () if isinstance(item, Mapping)
            )[-ACTION_CYCLE_HISTORY_CAP:],
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


@dataclass(frozen=True)
class CandidatePerformanceEvidence:
    """Canonical CUMULATIVE candidate-level performance aggregate, computed
    fresh each time from ``StrategyCandidateRecord.breadth_evidence`` (never
    persisted separately, so it can never drift out of sync with the
    symbol-keyed evidence it is derived from).

    Deliberately distinct from ``gaon.research.multi_symbol.
    UniverseResearchSummary``: that type is a single BATCH's local
    aggregate (one multi_symbol_research call, real production example:
    "5 symbols / 37 trades, median return -7.8%"). This type aggregates
    across EVERY distinct symbol this candidate has ever been validated
    against (real production example: "20 symbols / 149 trades" after four
    such batches) - the canonical number a promotion/rejection decision
    must be based on, not any single batch's local snapshot.
    """

    performance_sample_symbols: int
    performance_sample_trades: int
    median_return: float | None
    median_mdd: float | None
    profitable_symbol_ratio: float | None

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": STRATEGY_CANDIDATE_SCHEMA_VERSION,
            "performance_sample_symbols": self.performance_sample_symbols,
            "performance_sample_trades": self.performance_sample_trades,
            "median_return": self.median_return,
            "median_mdd": self.median_mdd,
            "profitable_symbol_ratio": self.profitable_symbol_ratio,
        }


def candidate_cumulative_performance(candidate: "StrategyCandidateRecord") -> CandidatePerformanceEvidence:
    """Computes this candidate's canonical cumulative performance aggregate
    from its symbol-keyed ``breadth_evidence`` (deduplicated by construction
    - each symbol occupies exactly one dict entry, so replaying the same
    symbol in a later batch overwrites its entry instead of double-counting
    it). Only symbols with real recorded performance evidence (eligible,
    traded, and carrying a non-``None`` ``total_return`` - see
    ``_normalize_breadth_evidence_detail``) contribute; legacy candidate
    records persisted before this field existed contribute none, so this
    honestly returns ``None`` medians/ratio rather than fabricating a
    performance read from breadth counts alone.
    """
    returns: list[float] = []
    mdds: list[float] = []
    profitable_count = 0
    trade_total = 0
    for detail in candidate.breadth_evidence.values():
        if not bool(detail.get("eligible")):
            continue
        trades = int(detail.get("trade_count", 0) or 0)
        total_return = detail.get("total_return")
        if trades <= 0 or total_return is None:
            continue
        returns.append(float(total_return))
        mdd = detail.get("mdd")
        if mdd is not None:
            mdds.append(float(mdd))
        if bool(detail.get("profitable")):
            profitable_count += 1
        trade_total += trades
    sample_size = len(returns)
    return CandidatePerformanceEvidence(
        performance_sample_symbols=sample_size,
        performance_sample_trades=trade_total,
        median_return=_median(returns),
        median_mdd=_median(mdds) if mdds else None,
        profitable_symbol_ratio=round(profitable_count / sample_size, 6) if sample_size else None,
    )


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


@dataclass(frozen=True)
class EconomicViabilityPolicy:
    """Explicit, bounded, project-owned economic-viability policy (see
    ECONOMIC_VIABILITY_* constants above for the rationale). Deliberately a
    configuration object, not inline magic numbers, so it is independently
    testable and adjustable without touching the decision logic below."""

    min_symbol_sample: int = ECONOMIC_VIABILITY_MIN_SYMBOL_SAMPLE
    min_trade_sample: int = ECONOMIC_VIABILITY_MIN_TRADE_SAMPLE
    min_profitable_symbol_ratio: float = ECONOMIC_VIABILITY_MIN_PROFITABLE_SYMBOL_RATIO


DEFAULT_ECONOMIC_VIABILITY_POLICY = EconomicViabilityPolicy()


@dataclass(frozen=True)
class EconomicViabilityResult:
    status: EconomicViabilityStatus
    reason: str
    performance: CandidatePerformanceEvidence

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": STRATEGY_CANDIDATE_SCHEMA_VERSION,
            "status": self.status.value,
            "reason": self.reason,
            "performance": self.performance.to_json(),
        }


def evaluate_economic_viability(
    candidate: "StrategyCandidateRecord",
    policy: EconomicViabilityPolicy = DEFAULT_ECONOMIC_VIABILITY_POLICY,
) -> EconomicViabilityResult:
    """Absolute profitability/risk verdict, separate from and in addition to
    robustness stage completion (see candidate_remaining_blockers). This is
    the gate KR-ST-008-shaped candidates were missing: a candidate can pass
    every robustness stage and still fail HERE if its own cumulative evidence
    shows it loses money.

    Three outcomes, never two, because a candidate with real but still-thin
    evidence must be allowed to keep gathering MORE evidence rather than
    being forced into a premature accept/reject call:
    - PASS: cumulative median return is positive AND at least
      ``min_profitable_symbol_ratio`` of validated symbols were individually
      profitable. Both signals must agree - "better than before" is not
      viability, and a positive median driven by one outlier symbol is not
      either.
    - FAIL: cumulative median return is non-positive AND fewer than
      ``min_profitable_symbol_ratio`` of validated symbols were profitable -
      both signals agree the candidate is a structural loser, only once
      ``policy``'s sample-size floor is met.
    - NEEDS_MORE_EVIDENCE: either the sample is still below policy's floor,
      no performance evidence has been recorded at all (e.g. a legacy
      candidate, or a candidate still purely in the breadth-gathering
      stage), or the two signals disagree (e.g. a positive median driven by
      an unrepresentative few symbols) - bounded sample expansion should
      continue rather than forcing a premature verdict either way.
    """
    performance = candidate_cumulative_performance(candidate)
    # Independent-review fix: the sample-size floor must be measured against
    # the REAL performance-evidence sample (performance.performance_sample_*
    # - symbols that actually carry a recorded total_return), not
    # candidate.valid_symbols/trade_count. Those breadth-level counters
    # include every eligible symbol, even ones with trade_count=0 (quality-
    # passed but never traded) or a legacy-migrated entry with no
    # total_return at all - a candidate could reach 20 "valid" symbols where
    # only 3 ever carried a real return/MDD figure and still clear this
    # floor, letting a 3-symbol sample force a FAIL verdict the module's own
    # design explicitly says must not happen ("a 5-symbol/41-trade batch is
    # real evidence but not enough").
    if performance.performance_sample_symbols < policy.min_symbol_sample or performance.performance_sample_trades < policy.min_trade_sample:
        return EconomicViabilityResult(EconomicViabilityStatus.NEEDS_MORE_EVIDENCE, "insufficient_breadth_for_economic_decision", performance)
    if performance.median_return is None or performance.profitable_symbol_ratio is None:
        return EconomicViabilityResult(EconomicViabilityStatus.NEEDS_MORE_EVIDENCE, "no_performance_evidence_recorded", performance)
    profitable = performance.median_return > 0 and performance.profitable_symbol_ratio >= policy.min_profitable_symbol_ratio
    unprofitable = performance.median_return <= 0 and performance.profitable_symbol_ratio < policy.min_profitable_symbol_ratio
    if profitable:
        return EconomicViabilityResult(EconomicViabilityStatus.PASS, "positive_median_return_and_majority_profitable_symbols", performance)
    if unprofitable:
        return EconomicViabilityResult(EconomicViabilityStatus.FAIL, "non_positive_median_return_and_minority_profitable_symbols", performance)
    return EconomicViabilityResult(EconomicViabilityStatus.NEEDS_MORE_EVIDENCE, "mixed_profitability_signal", performance)


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
        breadth_evidence={},
        breadth_legacy_trade_count=0,
        sample_exhaustion_reason=None,
        breadth_summary={},
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
    evidence_details: Mapping[str, Mapping[str, object]] | None = None,
    sample_exhaustion_reason: str | None = None,
    breadth_summary: Mapping[str, object] | None = None,
) -> StrategyCandidateRecord:
    """Records one cross-symbol (breadth) evaluation cycle's outcome.

    A provider/data-acquisition-blocked cycle (see
    ``gaon.knowledge.research_mission.is_provider_acquisition_blocker``)
    never counts toward stagnation - a strategy is never penalized for a
    data outage.
    """
    if evidence_details is None:
        merged_evidence_symbols = tuple(dict.fromkeys((*candidate.evidence_symbols, *evidence_symbols)))[:BREADTH_EVIDENCE_SYMBOL_CAP]
        merged_excluded_symbols = tuple(dict.fromkeys((*candidate.excluded_symbols, *excluded_symbols)))[:BREADTH_EVIDENCE_SYMBOL_CAP]
        canonical_attempted = max(candidate.attempted_symbols, attempted, len(merged_evidence_symbols) + len(merged_excluded_symbols))
        canonical_valid = max(candidate.valid_symbols, valid, len(merged_evidence_symbols))
        canonical_trade_count = max(candidate.trade_count, trade_count)
        canonical_breadth_evidence = dict(candidate.breadth_evidence)
        canonical_legacy_trade_count = candidate.breadth_legacy_trade_count
    else:
        canonical_breadth_evidence = _seed_breadth_evidence(candidate)
        for symbol, detail in evidence_details.items():
            normalized = _normalize_breadth_evidence_detail(symbol, detail)
            canonical_breadth_evidence[symbol] = normalized
        for symbol in excluded_symbols:
            canonical_breadth_evidence.setdefault(
                str(symbol),
                {"symbol": str(symbol), "eligible": False, "trade_count": 0, "source": "multi_symbol_research"},
            )
        canonical_breadth_evidence = dict(list(canonical_breadth_evidence.items())[:BREADTH_EVIDENCE_SYMBOL_CAP])
        canonical_legacy_trade_count = candidate.breadth_legacy_trade_count
        canonical_attempted = len(canonical_breadth_evidence)
        merged_evidence_symbols = tuple(
            symbol for symbol, detail in canonical_breadth_evidence.items() if bool(detail.get("eligible"))
        )
        merged_excluded_symbols = tuple(
            symbol for symbol, detail in canonical_breadth_evidence.items() if not bool(detail.get("eligible"))
        )
        canonical_valid = len(merged_evidence_symbols)
        canonical_trade_count = canonical_legacy_trade_count + sum(
            int(detail.get("trade_count", 0) or 0)
            for detail in canonical_breadth_evidence.values()
            if bool(detail.get("eligible"))
        )
    progressed = (
        canonical_valid > candidate.valid_symbols
        or canonical_trade_count > candidate.trade_count
        or tuple(merged_evidence_symbols) != tuple(candidate.evidence_symbols)
    )
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
        attempted_symbols=canonical_attempted,
        valid_symbols=canonical_valid,
        trade_count=canonical_trade_count,
        evidence_symbols=merged_evidence_symbols,
        excluded_symbols=merged_excluded_symbols,
        cycles_completed=candidate.cycles_completed + 1,
        cycles_without_progress=cycles_without_progress,
        status=status,
        updated_at=now,
        breadth_evidence=canonical_breadth_evidence,
        breadth_legacy_trade_count=canonical_legacy_trade_count,
        sample_exhaustion_reason=sample_exhaustion_reason or candidate.sample_exhaustion_reason,
        breadth_summary=dict(breadth_summary or candidate.breadth_summary),
    )


def _seed_breadth_evidence(candidate: StrategyCandidateRecord) -> dict[str, Mapping[str, object]]:
    if candidate.breadth_evidence:
        return {str(symbol): dict(detail) for symbol, detail in candidate.breadth_evidence.items()}
    seeded: dict[str, Mapping[str, object]] = {}
    for symbol in candidate.evidence_symbols:
        seeded[str(symbol)] = {"symbol": str(symbol), "eligible": True, "trade_count": 0, "source": "legacy_candidate_state"}
    for symbol in candidate.excluded_symbols:
        seeded.setdefault(
            str(symbol),
            {"symbol": str(symbol), "eligible": False, "trade_count": 0, "source": "legacy_candidate_state"},
        )
    return seeded


def _normalize_breadth_evidence_detail(symbol: str, detail: Mapping[str, object]) -> Mapping[str, object]:
    """Normalizes one symbol's raw multi-symbol-research evidence into this
    candidate's canonical, symbol-keyed record.

    Root cause fix (see ECONOMIC_VIABILITY_* above): this used to drop
    ``detail["metrics"]`` entirely after reading ``trade_count`` out of it,
    even though the real engine (``gaon.research.multi_symbol.
    aggregate_symbol_evidence``) already computes ``total_return``/``mdd``
    per symbol - those numbers reached this function and were then
    discarded, so no persisted candidate state ever remembered whether its
    own validated symbols made or lost money. ``total_return``/``mdd``/
    ``profitable`` are now carried through unchanged (never invented: a
    symbol whose engine result never reported a return, e.g. an excluded/
    untraded symbol, keeps ``total_return=None``/``mdd=None``/
    ``profitable=None`` rather than defaulting to 0.0, which would silently
    fabricate a break-even result).
    """
    metrics = detail.get("metrics") if isinstance(detail.get("metrics"), Mapping) else {}
    trade_count = detail.get("trade_count")
    if trade_count is None:
        trade_count = dict(metrics).get("trade_count", 0)
    total_return = detail.get("total_return")
    if total_return is None:
        total_return = dict(metrics).get("total_return")
    mdd = detail.get("mdd")
    if mdd is None:
        mdd = dict(metrics).get("mdd")
    eligible = bool(detail.get("eligible"))
    trade_count_int = int(trade_count or 0)
    total_return_value = float(total_return) if total_return is not None else None
    mdd_value = float(mdd) if mdd is not None else None
    has_performance_evidence = eligible and trade_count_int > 0 and total_return_value is not None
    return {
        "symbol": symbol,
        "eligible": eligible,
        "trade_count": trade_count_int,
        "total_return": total_return_value,
        "mdd": mdd_value,
        "profitable": (total_return_value > 0) if has_performance_evidence else None,
        "evidence_id": str(detail.get("evidence_id", "")),
        "quality_status": str(detail.get("quality_status", "")),
        "source": str(detail.get("source", "")),
        "fixture_backed": bool(detail.get("fixture_backed", False)),
    }


def record_robustness_progress(
    candidate: StrategyCandidateRecord,
    *,
    director_action: str,
    terminal: bool,
    now: str,
    validation_stage_status: Mapping[str, str] | None = None,
    symbol: str | None = None,
    reference: str | None = None,
) -> StrategyCandidateRecord:
    """Records one deep (single-symbol-anchored OOS/walk-forward/regime/
    cost/Monte Carlo) robustness cycle's outcome - the symbol used to run
    this cycle is evidence FOR this candidate, not a new identity; callers
    are responsible for choosing that symbol from the candidate's own
    validated evidence set.

    ``validation_stage_status`` (Patch 8.5), when given, is merged
    key-by-key into the candidate's persisted per-stage status - a stage
    absent from this call's status (e.g. a cycle that only advanced OOS)
    leaves any PREVIOUSLY recorded status for other stages untouched,
    rather than resetting them to unknown.

    ``symbol`` (Patch 8.6), when given, is the real evaluation sample this
    cycle used - it is recorded (bounded, de-duplicated) into
    ``robustness_evidence_symbols`` and ``last_validation_symbol`` so a
    later terminal, non-promoting, non-rejecting decision (e.g. hold) can
    rotate to a DIFFERENT, not-yet-tried evidence symbol via
    ``next_robustness_evidence_symbol`` instead of losing its place or
    repeating the same symbol. Left ``None`` (e.g. when the caller could
    not verify this cycle actually validated the candidate's own effective
    rules) leaves this candidate's evidence-symbol memory untouched, so an
    unverified cycle is never counted as robustness evidence."""
    new_symbol = bool(symbol and symbol not in candidate.robustness_evidence_symbols)
    stage_changed = False
    if validation_stage_status:
        stage_changed = any(
            str(candidate.validation_stage_status.get(str(key), "")) != str(value)
            for key, value in validation_stage_status.items()
        )
    terminal_progress = terminal and director_action in {"request_human_promotion_review", "reject_candidate"}
    progressed = new_symbol or stage_changed or terminal_progress
    cycles_without_progress = 0 if progressed else candidate.cycles_without_progress + 1
    status = candidate.status if terminal else StrategyCandidateStatus.ROBUSTNESS
    merged_stage_status = dict(candidate.validation_stage_status)
    if validation_stage_status:
        merged_stage_status.update({str(key): str(value) for key, value in validation_stage_status.items()})
    robustness_evidence_symbols = candidate.robustness_evidence_symbols
    robustness_attempt_count = candidate.robustness_attempt_count
    last_validation_symbol = candidate.last_validation_symbol
    if symbol:
        robustness_evidence_symbols = tuple(
            dict.fromkeys((*candidate.robustness_evidence_symbols, symbol))
        )[:ROBUSTNESS_EVIDENCE_SYMBOL_CAP]
        robustness_attempt_count = candidate.robustness_attempt_count + 1
        last_validation_symbol = symbol
    attempt_action = _action_from_reference(reference) or director_action
    attempt_stage = ACTION_STAGE_KEYS.get(attempt_action, "")
    state_key = candidate_material_evidence_key(candidate)
    result_state_key = candidate_material_evidence_key(
        replace(
            candidate,
            status=status,
            validation_stage_status=merged_stage_status,
            robustness_evidence_symbols=robustness_evidence_symbols,
            robustness_attempt_count=robustness_attempt_count,
            last_validation_symbol=last_validation_symbol,
        )
    )
    validation_attempt_history = candidate.validation_attempt_history
    if attempt_action in ACTION_STAGE_KEYS:
        validation_attempt_history = (
            *candidate.validation_attempt_history,
            {
                "action": attempt_action,
                "stage": attempt_stage,
                "symbol": symbol or "",
                "state_key": state_key,
                "result_state_key": result_state_key,
                "progressed": progressed,
                "reference": reference or "",
            },
        )[-ACTION_CYCLE_HISTORY_CAP:]
    return replace(
        candidate,
        last_director_action=director_action,
        cycles_completed=candidate.cycles_completed + 1,
        cycles_without_progress=cycles_without_progress,
        status=status,
        validation_stage_status=merged_stage_status,
        robustness_evidence_symbols=robustness_evidence_symbols,
        robustness_attempt_count=robustness_attempt_count,
        last_validation_symbol=last_validation_symbol,
        last_validation_reference=reference if reference is not None else candidate.last_validation_reference,
        validation_attempt_history=validation_attempt_history,
        updated_at=now,
    )


def next_robustness_evidence_symbol(candidate: StrategyCandidateRecord, *, exclude: str | None = None) -> str | None:
    """Picks the next symbol from this candidate's own BREADTH-validated
    evidence pool (``evidence_symbols``) that has not yet been used as a
    ROBUSTNESS (deep single-symbol) evaluation sample, so a market-wide
    robustness mission actually progresses across multiple symbols under
    the SAME strategy_fingerprint (Patch 8.6) instead of only ever
    deepening one. ``exclude`` additionally skips the symbol just used this
    cycle even if it has not yet been persisted into
    ``robustness_evidence_symbols`` (e.g. because this cycle's identity
    could not be verified). Returns ``None`` once every known evidence
    symbol has already been tried - callers should then fall back to
    gathering more breadth evidence rather than repeating a symbol."""
    tried = set(candidate.robustness_evidence_symbols)
    if exclude:
        tried.add(exclude)
    for symbol in candidate.evidence_symbols:
        if symbol not in tried:
            return symbol
    return None


def candidate_progress_signature(candidate: StrategyCandidateRecord) -> tuple[object, ...]:
    """Deterministic, evidence-bound signature for meaningful candidate
    progress. A Research Director action label changing is not enough:
    progression requires new independent evidence, more samples, a changed
    validation stage, or a real terminal decision."""
    return (
        candidate.status.value,
        candidate.valid_symbols,
        candidate.trade_count,
        tuple(candidate.evidence_symbols),
        tuple(candidate.robustness_evidence_symbols),
        tuple(sorted((str(key), str(value)) for key, value in candidate.validation_stage_status.items())),
        candidate.promotion_ready_at or "",
        candidate.rejected_reason or "",
    )


def candidate_material_evidence_key(candidate: StrategyCandidateRecord) -> str:
    """State identity for action-cycle suppression.

    Deliberately excludes presentation fields, timestamps, last attempted
    action, and counters. If the candidate gains new sample breadth, a new
    robustness symbol, changed validation status, or terminal evidence, the
    key changes and a previously exhausted validation action may be tried
    again under the new evidence state.
    """
    return "|".join(
        (
            candidate.strategy_fingerprint,
            str(candidate.valid_symbols),
            str(candidate.trade_count),
            ",".join(candidate.evidence_symbols),
            ",".join(candidate.excluded_symbols),
            ",".join(candidate.robustness_evidence_symbols),
            ",".join(f"{key}={value}" for key, value in sorted(candidate.validation_stage_status.items())),
            candidate.sample_exhaustion_reason or "",
            candidate.promotion_ready_at or "",
            candidate.rejected_reason or "",
        )
    )


def candidate_remaining_blockers(candidate: StrategyCandidateRecord) -> tuple[str, ...]:
    """Returns unresolved candidate blockers from persisted authoritative state.

    This is deliberately a read model over StrategyCandidateRecord. It never
    runs validation, fabricates a stage, or treats presentation text as state.
    """
    blockers: list[str] = []
    if not candidate.has_sufficient_universe_evidence:
        blockers.append("multi_symbol_sample")
    if candidate.trade_count < PROMOTION_MIN_TRADE_SAMPLE:
        blockers.append("minimum_trade_sample")
    stage_status = dict(candidate.validation_stage_status)
    required_stages = (
        "out_of_sample",
        "regime_validation",
        "walk_forward",
        "parameter_sensitivity",
        "transaction_cost_stress",
    )
    for stage in required_stages:
        status = str(stage_status.get(stage, "not_run"))
        if status not in PASS_LIKE_STAGE_STATUSES:
            blockers.append(stage)
    monte_carlo = str(stage_status.get("monte_carlo", "not_run"))
    if monte_carlo not in PASS_LIKE_STAGE_STATUSES:
        if candidate.trade_count < PROMOTION_MIN_TRADE_SAMPLE:
            blockers.append("monte_carlo_waiting_for_primary_sample")
        else:
            blockers.append("monte_carlo")
    return tuple(dict.fromkeys(blockers))


def next_blocker_driven_research_action(candidate: StrategyCandidateRecord) -> tuple[str, str]:
    """Selects the next bounded execution action from persisted blockers.

    The returned action must be consumed by the next continuation executor;
    callers should not render it as advisory-only presentation text.
    """
    if candidate.status is StrategyCandidateStatus.PROMOTION_READY:
        return "REQUEST_HUMAN_APPROVAL", "candidate_already_promotion_ready"
    if candidate.status in (StrategyCandidateStatus.REJECTED, StrategyCandidateStatus.STAGNANT):
        return "ROTATE_CANDIDATE", candidate.rejected_reason or "candidate_terminal"
    # Root cause fix (see ECONOMIC_VIABILITY_* above): an economic-viability
    # FAIL takes priority over every remaining robustness/breadth blocker,
    # including EXPAND_SAMPLE. Robustness stages measure whether the
    # evidence is trustworthy; they say nothing about whether it is
    # profitable. Checked BEFORE the breadth-sufficiency/EXPAND_SAMPLE
    # branches below so a candidate with decisively negative cumulative
    # economics is rotated out the moment that becomes clear, instead of
    # continuing to expand its sample toward the whole candidate pool.
    economic_viability = evaluate_economic_viability(candidate)
    if economic_viability.status is EconomicViabilityStatus.FAIL:
        return "ROTATE_CANDIDATE", f"economic_viability_failed:{economic_viability.reason}"
    blockers = candidate_remaining_blockers(candidate)
    next_symbol = next_robustness_evidence_symbol(candidate)
    sample_exhausted = candidate_sample_exhausted(candidate)
    if not sample_exhausted and (not candidate.has_sufficient_universe_evidence or not next_symbol):
        return "EXPAND_SAMPLE", "need_new_independent_evidence_symbols"
    if sample_exhausted and not candidate.has_sufficient_universe_evidence:
        return "ROTATE_CANDIDATE", candidate.sample_exhaustion_reason or "sample_pool_exhausted_without_sufficient_evidence"
    exhausted_actions = _attempted_actions_for_current_evidence_state(candidate)
    for blocker, action, reason in (
        ("out_of_sample", "RUN_OOS", "out_of_sample_blocker"),
        ("regime_validation", "RUN_REGIME", "regime_blocker"),
        ("walk_forward", "RUN_WALK_FORWARD", "walk_forward_blocker"),
        ("transaction_cost_stress", "RUN_COST_STRESS", "transaction_cost_blocker"),
        ("parameter_sensitivity", "RUN_SENSITIVITY", "parameter_sensitivity_blocker"),
    ):
        if blocker not in blockers:
            continue
        if action in exhausted_actions:
            continue
        if _last_attempt_matches_stage(candidate, action, blocker):
            continue
        if sample_exhausted and next_symbol is None:
            return "ROTATE_CANDIDATE", "sample_pool_exhausted_no_untried_robustness_symbol"
        return action, reason
    if "monte_carlo_waiting_for_primary_sample" in blockers:
        if sample_exhausted:
            return "ROTATE_CANDIDATE", "sample_pool_exhausted_below_monte_carlo_sample"
        return "EXPAND_SAMPLE", "monte_carlo_waiting_for_primary_sample"
    if "monte_carlo" in blockers and "RUN_MONTE_CARLO" not in exhausted_actions and not _last_attempt_matches_stage(candidate, "RUN_MONTE_CARLO", "monte_carlo"):
        if sample_exhausted and next_symbol is None:
            return "ROTATE_CANDIDATE", "sample_pool_exhausted_no_untried_robustness_symbol"
        return "RUN_MONTE_CARLO", "monte_carlo_blocker"
    if any(blocker in blockers for blocker in ACTION_STAGE_KEYS.values()):
        if candidate.cycles_without_progress >= STAGNATION_CYCLE_THRESHOLD:
            return "ROTATE_CANDIDATE", "validation_cycle_exhausted_without_progress"
        if sample_exhausted:
            return "ROTATE_CANDIDATE", "sample_pool_exhausted_after_attempted_validation_dimensions"
        return "EXPAND_SAMPLE", "validation_cycle_exhausted_needs_new_material_evidence"
    # Every robustness/breadth blocker is cleared, but a PASS verdict (see
    # evaluate_economic_viability) has not actually been reached yet - e.g.
    # robustness finished on a candidate whose breadth sample is still below
    # the (higher) economic-decision sample floor. RANK_CANDIDATES ->
    # eventual promotion must never be reached on robustness completion
    # alone (item D: promotion-ready requires economic viability AND
    # robustness AND sufficient sample, not any one of them).
    if economic_viability.status is EconomicViabilityStatus.NEEDS_MORE_EVIDENCE:
        if sample_exhausted:
            return "ROTATE_CANDIDATE", "sample_pool_exhausted_insufficient_economic_evidence"
        return "EXPAND_SAMPLE", "economic_viability_needs_more_evidence"
    return "RANK_CANDIDATES", "no_blocking_validation_stage_remaining"


def _attempted_actions_for_current_evidence_state(candidate: StrategyCandidateRecord) -> frozenset[str]:
    """Validation actions already consumed under this evidence revision.

    A prior action may have ``progressed=True`` because it changed a stage
    from ``not_run``/``partial`` into a decisive failure such as
    ``fail_underperformed_baseline``. That action still consumed the current
    evidence revision: rerunning it immediately after another no-op blocker
    would be the same research, not new evidence. We therefore match both
    the pre-attempt state key used by no-progress attempts and the
    post-attempt ``result_state_key`` introduced for decisive/progressing
    validation outcomes. Once breadth, sample, fingerprint, or validation
    evidence changes, the material key changes and the action can become
    eligible again.
    """
    state_key = candidate_material_evidence_key(candidate)
    return frozenset(
        str(item.get("action"))
        for item in candidate.validation_attempt_history
        if str(item.get("state_key", "")) == state_key or str(item.get("result_state_key", "")) == state_key
    )


def _action_from_reference(reference: str | None) -> str | None:
    if not reference:
        return None
    for part in str(reference).split("|"):
        if part.startswith("action="):
            action = part.split("=", 1)[1]
            return action or None
    return None


def candidate_sample_exhausted(candidate: StrategyCandidateRecord) -> bool:
    return str(candidate.sample_exhaustion_reason or "") in {
        "candidate_pool_exhausted",
        "configured_sample_budget_exhausted",
        "no_new_independent_symbols_available",
    }


def _last_attempt_matches_stage(candidate: StrategyCandidateRecord, action: str, stage: str) -> bool:
    symbol = candidate.last_validation_symbol
    if not symbol:
        return False
    status = str(candidate.validation_stage_status.get(stage, "not_run"))
    reference = f"action={action}|symbol={symbol}|stage={stage}|status={status}"
    return candidate.last_validation_reference == reference


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
        f"fingerprint: {candidate.strategy_fingerprint[:16]}",
    ]
    if candidate.attempted_symbols:
        lines.append(f"검증 표본: 유효 {candidate.valid_symbols}종목 / 시도 {candidate.attempted_symbols}종목")
    if candidate.trade_count:
        lines.append(f"거래 표본: {candidate.trade_count}건")
    lines.append(f"상태: {_STATUS_LABELS_KO.get(candidate.status, candidate.status.value)}")
    if candidate.last_director_action:
        lines.append(f"최근 검증 단계: {candidate.last_director_action}")
    return "\n".join(lines)


def _pct_or_na(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "N/A"


_ROBUSTNESS_STAGE_BLOCKERS = frozenset({*ACTION_STAGE_KEYS.values(), "monte_carlo_waiting_for_primary_sample"})


def render_candidate_cumulative_evidence_block(candidate: StrategyCandidateRecord) -> str:
    """Renders the CANONICAL cumulative candidate-level evidence and the
    resulting economic-viability/robustness/next-action decision - item E's
    "[누적 후보 evidence]"/"[후보 판단]" sections. Deliberately separate from
    whatever a single batch's own report already shows (e.g.
    ``gaon.research.multi_symbol.MultiSymbolResearchRun.korean_report``,
    rendered as "[이번 batch]" alongside this by the caller), and computed
    fresh from persisted state every call - it is a read model, never a
    second source of truth that could drift from ``breadth_evidence``."""
    performance = candidate_cumulative_performance(candidate)
    viability = evaluate_economic_viability(candidate)
    remaining_blockers = candidate_remaining_blockers(candidate)
    stage_blockers = tuple(blocker for blocker in remaining_blockers if blocker in _ROBUSTNESS_STAGE_BLOCKERS)
    robustness_label = "pass" if not stage_blockers else ",".join(stage_blockers)
    decision, decision_reason = next_blocker_driven_research_action(candidate)
    lines = [
        "[누적 후보 evidence]",
        f"- {candidate.valid_symbols} symbols / {candidate.trade_count} trades",
        f"- cumulative median return: {_pct_or_na(performance.median_return)}",
        f"- cumulative median MDD: {_pct_or_na(performance.median_mdd)}",
        f"- profitable symbol ratio: {_pct_or_na(performance.profitable_symbol_ratio)}",
        "",
        "[후보 판단]",
        f"- economic viability: {viability.status.value}",
        f"- robustness: {robustness_label}",
        f"- decision: {decision}",
        f"- reason: {decision_reason}",
    ]
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


# Patch 8.8: human-readable entry/filter/exit descriptions for the rule
# keys ``build_candidate_spec``'s templates actually produce (see
# STRATEGY_FAMILY_TEMPLATES above). A key not listed here still renders
# (as "{key}={value}") rather than being silently dropped - this module
# never guesses a description for a rule it does not recognize.
_ENTRY_RULE_LABELS: Mapping[str, str] = {
    "breakout_lookback": "{value}일 신고가 돌파 시 진입",
}
_EXIT_RULE_LABELS: Mapping[str, str] = {
    "protective_stop_pct": "진입가 대비 {value}% 손절",
    "channel_exit_lookback": "{value}일 채널 저점 이탈 시 청산",
}
_FILTER_RULE_LABELS: Mapping[str, str] = {
    "close_gt_ma20": "종가가 MA20 위에 있어야 진입 (추세 필터)",
    "ma20_gt_ma60": "MA20이 MA60보다 높아야 진입 (장기 추세 필터)",
    "volume_gte_ma20": "거래량이 20일 평균 거래량 이상이어야 진입",
}


def _describe_rule_section(rules: Mapping[str, object], labels: Mapping[str, str]) -> list[str]:
    lines: list[str] = []
    for key in sorted(rules):
        raw = rules[key]
        value = raw.get("value") if isinstance(raw, Mapping) else raw
        if value is False or value is None:
            continue
        label = labels.get(key)
        if label is None:
            lines.append(f"- {key}={value}")
        elif "{value}" in label:
            lines.append(f"- {label.format(value=value)}")
        else:
            lines.append(f"- {label}")
    return lines


def render_candidate_strategy_explanation(candidate: StrategyCandidateRecord) -> str:
    """Human-readable entry/filter/exit explanation of ``candidate``'s own
    ``spec_rules`` ONLY (Patch 8.8 production bug fix) - never a stale
    single-symbol backtest result, never a rule this candidate does not
    actually have. Answers "현재 단타 전략을 설명해주세요" while a mission-
    tracked candidate is active, from the same canonical rules
    ``multi_symbol_research`` evaluates this candidate against."""
    rules = candidate.spec_rules or {}
    entry = rules.get("entry") or {}
    exit_rules = rules.get("exit") or {}
    filters = rules.get("filters") or {}
    lines = [
        f"[전략 후보 {candidate.candidate_id}]",
        f"전략 계열: {candidate.hypothesis_summary} ({candidate.strategy_family})",
        f"fingerprint: {candidate.strategy_fingerprint[:16]}",
        "",
        "[진입 조건]",
        *(_describe_rule_section(entry, _ENTRY_RULE_LABELS) or ["- (기록된 진입 규칙 없음)"]),
    ]
    filter_lines = _describe_rule_section(filters, _FILTER_RULE_LABELS)
    if filter_lines:
        lines.append("")
        lines.append("[필터 조건]")
        lines.extend(filter_lines)
    lines.append("")
    lines.append("[청산 조건]")
    lines.extend(_describe_rule_section(exit_rules, _EXIT_RULE_LABELS) or ["- (기록된 청산 규칙 없음)"])
    return "\n".join(lines)


def _raise_if_failed(label: str, checks: Mapping[str, bool]) -> None:
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"{label} release check failed: {failed}")


def production_economic_viability_gate_release_check() -> Mapping[str, object]:
    """Deterministic regression proving the KR-ST-008-shaped production
    defect (see the comment above ECONOMIC_VIABILITY_MIN_SYMBOL_SAMPLE) is
    closed: a candidate whose cumulative cross-symbol evidence is
    decisively unprofitable is rejected instead of EXPAND_SAMPLE running
    forever, while a genuinely borderline/positive candidate is still
    allowed bounded sample expansion and, once robustness is also
    satisfied, reaches RANK_CANDIDATES - never an auto-promotion, that
    still requires the separate human-gated step this module never
    performs itself.

    Replays the real reported trace: batch 1 (5 symbols/41 trades, median
    return -20.2%, MDD 46.0%) -> batch 2 (+5/34 trades, -23.0%, 35.4%) ->
    batch 3 (+5/37 trades, +1.4%, 47.1%) -> batch 4 (+5/37 trades, -7.8%,
    41.9%), reaching the real reported canonical cumulative breadth of 20
    symbols / 149 trades.
    """
    now = "2026-08-22T00:00:00Z"
    candidate = new_candidate("breakout_slow_trend_confirmed", sequence=8, now=now)

    # Real reported per-batch data. Per-symbol return/MDD values within each
    # batch are chosen so each batch's OWN median return/MDD reproduces the
    # real reported batch-level figures exactly (batches only ever reported
    # medians, never every symbol's individual result).
    batches: tuple[tuple[tuple[str, int, float, float], ...], ...] = (
        (
            ("KR001", 8, -0.35, 0.30), ("KR002", 8, -0.25, 0.40), ("KR003", 8, -0.202, 0.46),
            ("KR004", 8, -0.15, 0.50), ("KR005", 9, -0.05, 0.60),
        ),
        (
            ("KR006", 7, -0.40, 0.20), ("KR007", 7, -0.30, 0.30), ("KR008", 7, -0.23, 0.354),
            ("KR009", 6, -0.10, 0.40), ("KR010", 7, 0.05, 0.45),
        ),
        (
            ("KR011", 7, -0.10, 0.30), ("KR012", 7, -0.02, 0.40), ("KR013", 8, 0.014, 0.471),
            ("KR014", 7, 0.05, 0.55), ("KR015", 8, 0.20, 0.60),
        ),
        (
            ("KR016", 7, -0.30, 0.25), ("KR017", 7, -0.15, 0.35), ("KR018", 8, -0.078, 0.419),
            ("KR019", 7, -0.02, 0.45), ("KR020", 8, 0.10, 0.55),
        ),
    )
    expected_cumulative_symbols = (5, 10, 15, 20)
    expected_cumulative_trades = (41, 75, 112, 149)
    per_batch_decisions: list[tuple[str, str]] = []
    for index, batch in enumerate(batches):
        evidence_details = {
            symbol: {"eligible": True, "trade_count": trades, "metrics": {"total_return": total_return, "mdd": mdd}}
            for symbol, trades, total_return, mdd in batch
        }
        candidate = record_breadth_progress(
            candidate,
            attempted=len(batch),
            valid=len(batch),
            trade_count=sum(trades for _, trades, _, _ in batch),
            evidence_symbols=tuple(symbol for symbol, _, _, _ in batch),
            excluded_symbols=(),
            provider_blocked=False,
            now=now,
            evidence_details=evidence_details,
            breadth_summary={"aggregate_trade_count": sum(trades for _, trades, _, _ in batch)},
        )
        assert candidate.valid_symbols == expected_cumulative_symbols[index]
        assert candidate.trade_count == expected_cumulative_trades[index]
        per_batch_decisions.append(next_blocker_driven_research_action(candidate))

    after_batch4 = candidate
    performance_after_batch4 = candidate_cumulative_performance(after_batch4)
    viability_after_batch4 = evaluate_economic_viability(after_batch4)
    action_after_batch4, reason_after_batch4 = next_blocker_driven_research_action(after_batch4)

    # Duplicate replay of an already-recorded batch (e.g. a retried
    # continuation) must never double-count that batch's symbols/trades.
    replayed = record_breadth_progress(
        after_batch4,
        attempted=len(batches[-1]),
        valid=len(batches[-1]),
        trade_count=sum(trades for _, trades, _, _ in batches[-1]),
        evidence_symbols=tuple(symbol for symbol, _, _, _ in batches[-1]),
        excluded_symbols=(),
        provider_blocked=False,
        now=now,
        evidence_details={
            symbol: {"eligible": True, "trade_count": trades, "metrics": {"total_return": total_return, "mdd": mdd}}
            for symbol, trades, total_return, mdd in batches[-1]
        },
    )

    # Even a candidate whose robustness stages are ALL reported PASS-like
    # must not be allowed to promote on a decisive economic-viability FAIL
    # (item D): robustness answers "was this measured honestly", not "is it
    # worth trading".
    robust_but_unprofitable = replace(
        after_batch4,
        validation_stage_status={
            "out_of_sample": "pass", "regime_validation": "pass", "walk_forward": "pass",
            "transaction_cost_stress": "cost_stable", "parameter_sensitivity": "stable", "monte_carlo": "pass",
        },
    )
    action_robust_but_unprofitable, reason_robust_but_unprofitable = next_blocker_driven_research_action(robust_but_unprofitable)

    # Restart persistence: the rejection verdict and the evidence behind it
    # must survive a to_json/from_json round trip unchanged.
    restarted = StrategyCandidateRecord.from_json(after_batch4.to_json())
    viability_after_restart = evaluate_economic_viability(restarted)

    # Legacy backward compatibility: a candidate persisted before this
    # patch (breadth counts only, no per-symbol return/MDD) must never be
    # scored as FAIL/PASS from fabricated performance data.
    legacy = StrategyCandidateRecord.from_json(
        {
            "candidate_id": "KR-ST-LEGACY", "strategy_fingerprint": "fp:legacy", "strategy_family": "breakout_standard",
            "status": "validating", "attempted_symbols": 20, "valid_symbols": 20, "trade_count": 150,
            "evidence_symbols": [f"LEG{i:02d}" for i in range(20)], "excluded_symbols": [],
            "created_at": now, "updated_at": now,
        }
    )
    legacy_viability = evaluate_economic_viability(legacy)

    # Opposite case: sufficient breadth, decisively positive economics, and
    # complete robustness reaches RANK_CANDIDATES - but never mutates status
    # to PROMOTION_READY itself (that stays a separate human-gated step).
    profitable_candidate = new_candidate("breakout_multi_confirmed", sequence=9, now=now)
    profitable_batch = tuple(
        (f"PR{i:02d}", 6, 0.08 if i % 2 == 0 else -0.02, 0.20) for i in range(20)
    )
    profitable_candidate = record_breadth_progress(
        profitable_candidate,
        attempted=len(profitable_batch),
        valid=len(profitable_batch),
        trade_count=sum(trades for _, trades, _, _ in profitable_batch),
        evidence_symbols=tuple(symbol for symbol, _, _, _ in profitable_batch),
        excluded_symbols=(),
        provider_blocked=False,
        now=now,
        evidence_details={
            symbol: {"eligible": True, "trade_count": trades, "metrics": {"total_return": total_return, "mdd": mdd}}
            for symbol, trades, total_return, mdd in profitable_batch
        },
    )
    profitable_candidate = replace(
        profitable_candidate,
        validation_stage_status={
            "out_of_sample": "pass", "regime_validation": "pass", "walk_forward": "pass",
            "transaction_cost_stress": "cost_stable", "parameter_sensitivity": "stable", "monte_carlo": "pass",
        },
    )
    profitable_viability = evaluate_economic_viability(profitable_candidate)
    profitable_action, _ = next_blocker_driven_research_action(profitable_candidate)

    checks = {
        "batch1_undersized_sample_never_forces_a_verdict": per_batch_decisions[0][0] != "ROTATE_CANDIDATE",
        "cumulative_breadth_matches_reported_trace": (after_batch4.valid_symbols, after_batch4.trade_count) == (20, 149),
        "cumulative_median_return_is_negative": performance_after_batch4.median_return is not None and performance_after_batch4.median_return < 0,
        "cumulative_profitable_ratio_is_minority": performance_after_batch4.profitable_symbol_ratio is not None and performance_after_batch4.profitable_symbol_ratio < 0.5,
        "economic_viability_fails_on_sufficient_negative_evidence": viability_after_batch4.status is EconomicViabilityStatus.FAIL,
        "decisive_failure_rotates_instead_of_expanding_forever": action_after_batch4 == "ROTATE_CANDIDATE" and action_after_batch4 != "EXPAND_SAMPLE",
        "rotation_reason_names_economic_viability": reason_after_batch4.startswith("economic_viability_failed"),
        "duplicate_symbol_replay_does_not_double_count": (replayed.valid_symbols, replayed.trade_count) == (20, 149),
        "robustness_pass_does_not_override_economic_fail": action_robust_but_unprofitable == "ROTATE_CANDIDATE" and reason_robust_but_unprofitable.startswith("economic_viability_failed"),
        "rejection_survives_restart": viability_after_restart.status is EconomicViabilityStatus.FAIL,
        "legacy_record_never_fabricates_a_verdict": legacy_viability.status is EconomicViabilityStatus.NEEDS_MORE_EVIDENCE,
        "profitable_candidate_passes_economic_viability": profitable_viability.status is EconomicViabilityStatus.PASS,
        "profitable_and_robust_candidate_reaches_ranking_not_auto_promotion": (
            profitable_action == "RANK_CANDIDATES" and profitable_candidate.status is not StrategyCandidateStatus.PROMOTION_READY
        ),
        "no_mutation_beyond_bookkeeping": after_batch4.status is not StrategyCandidateStatus.PROMOTION_READY,
    }
    _raise_if_failed("production economic viability gate", checks)
    return {
        "schema_version": STRATEGY_CANDIDATE_SCHEMA_VERSION,
        "cumulative_symbols": after_batch4.valid_symbols,
        "cumulative_trades": after_batch4.trade_count,
        "cumulative_median_return": performance_after_batch4.median_return,
        "cumulative_median_mdd": performance_after_batch4.median_mdd,
        "profitable_symbol_ratio": performance_after_batch4.profitable_symbol_ratio,
        "economic_viability": viability_after_batch4.status.value,
        "decision": action_after_batch4,
        "reason": reason_after_batch4,
        "safety": "pass",
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
    }
