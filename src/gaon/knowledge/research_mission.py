"""Patch 8.1 - Persistent Autonomous Research Mission.

A real Telegram conversation exposed a scope-regression defect: once a user
established a market-wide KR research scope ("코스피/코스닥 전체 종목을
연구해줘"), a later generic continuation message ("증거가 충분할 때까지
연구해주세요") silently collapsed back to a single symbol (005930, Samsung
Electronics) because the conversation layer only ever remembered
``last_symbols`` (a flat symbol list) and resolved a bare continuation to
``last_symbols[0]`` - see ``gaon.runtime.llm_conversation._resolve_autonomous_symbol``.
There was no persistent, explicit notion of *why* the user was researching or
*how broad* the research scope was supposed to stay.

This module adds that persistent state - a ``ResearchMission`` - without
introducing a second research engine. It only:

1. Extracts/updates a ``ResearchMission`` from user text (market, universe
   scope, target promotion-ready candidate count, objective).
2. Decides, from the existing scope, whether a generic continuation message
   ("계속 연구해주세요", "증거가 충분할 때까지", ...) should keep the
   established scope (mandatory scope-regression guard) rather than falling
   back to any single-symbol default.
3. Drives one bounded research cycle by calling the EXISTING
   ``gaon.research.multi_symbol.multi_symbol_research_payload`` (market-wide /
   multi-symbol research) and the EXISTING
   ``gaon.knowledge.telegram_autonomous_learning.telegram_autonomous_learning_payload``
   (single-symbol Autonomous Learning V2, which is the only engine that
   already runs the real ``PromotionCandidateGate``) to decide whether a
   researched symbol is promotion-ready, per the existing promotion criteria.
   Promotion criteria are never weakened here.
4. Never auto-promotes. Reaching the target candidate count only moves the
   mission to ``awaiting_human_approval`` - a human still has to approve via
   the existing human-gated promotion mechanism.

Persistence: a mission is stored as a JSON blob inside the same
``conversation_sessions.metadata_json`` column that already carries
``ConversationalMVPContext`` (see ``gaon.runtime.llm_conversation``), under a
sibling key (``research_mission``) of the existing ``last_research_context``.
No new database table is introduced - the existing durable, restart-safe
session metadata column is reused.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import re
from typing import Mapping
from uuid import uuid4


RESEARCH_MISSION_SCHEMA_VERSION = 1

DEFAULT_KR_EXCHANGES: tuple[str, ...] = ("KOSPI", "KOSDAQ")


class MissionUniverseScope(str, Enum):
    SINGLE_SYMBOL = "single_symbol"
    SELECTED_SYMBOLS = "selected_symbols"
    MARKET_WIDE = "market_wide"


class MissionStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"


@dataclass(frozen=True)
class ResearchMission:
    mission_id: str
    market: str
    universe_scope: MissionUniverseScope
    symbols: tuple[str, ...]
    exchanges: tuple[str, ...]
    strategy_family: str | None
    improve_return: bool
    improve_safety: bool
    baseline_comparison: str | None
    target_promotion_ready_candidates: int | None
    current_promotion_ready_candidates: int
    promotion_ready_candidates: tuple[Mapping[str, object], ...]
    explored_symbols: tuple[str, ...]
    status: MissionStatus
    blocked_reason: str | None
    cycles_completed: int
    created_at: str
    updated_at: str
    originating_request: str
    pending_promotion_symbol: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_MISSION_SCHEMA_VERSION,
            "mission_id": self.mission_id,
            "market": self.market,
            "universe_scope": self.universe_scope.value,
            "symbols": list(self.symbols),
            "exchanges": list(self.exchanges),
            "strategy_family": self.strategy_family,
            "objective": {
                "improve_return": self.improve_return,
                "improve_safety": self.improve_safety,
                "baseline_comparison": self.baseline_comparison,
            },
            "target_promotion_ready_candidates": self.target_promotion_ready_candidates,
            "current_promotion_ready_candidates": self.current_promotion_ready_candidates,
            "promotion_ready_candidates": [dict(item) for item in self.promotion_ready_candidates],
            "explored_symbols": list(self.explored_symbols),
            "status": self.status.value,
            "blocked_reason": self.blocked_reason,
            "cycles_completed": self.cycles_completed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "originating_request": self.originating_request,
            "pending_promotion_symbol": self.pending_promotion_symbol,
        }

    @staticmethod
    def from_json(raw: Mapping[str, object]) -> "ResearchMission":
        objective = raw.get("objective") if isinstance(raw.get("objective"), Mapping) else {}
        return ResearchMission(
            mission_id=str(raw["mission_id"]),
            market=str(raw.get("market", "KR")),
            universe_scope=MissionUniverseScope(str(raw.get("universe_scope", MissionUniverseScope.SINGLE_SYMBOL.value))),
            symbols=_tuple_of_str(raw.get("symbols")),
            exchanges=_tuple_of_str(raw.get("exchanges")) or DEFAULT_KR_EXCHANGES,
            strategy_family=str(raw["strategy_family"]) if raw.get("strategy_family") else None,
            improve_return=bool(objective.get("improve_return", False)),
            improve_safety=bool(objective.get("improve_safety", False)),
            baseline_comparison=str(objective["baseline_comparison"]) if objective.get("baseline_comparison") else None,
            target_promotion_ready_candidates=int(raw["target_promotion_ready_candidates"]) if raw.get("target_promotion_ready_candidates") is not None else None,
            current_promotion_ready_candidates=int(raw.get("current_promotion_ready_candidates", 0) or 0),
            promotion_ready_candidates=tuple(dict(item) for item in raw.get("promotion_ready_candidates", ()) if isinstance(item, Mapping)),
            explored_symbols=_tuple_of_str(raw.get("explored_symbols")),
            status=MissionStatus(str(raw.get("status", MissionStatus.ACTIVE.value))),
            blocked_reason=str(raw["blocked_reason"]) if raw.get("blocked_reason") else None,
            cycles_completed=int(raw.get("cycles_completed", 0) or 0),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            originating_request=str(raw.get("originating_request", "")),
            pending_promotion_symbol=str(raw["pending_promotion_symbol"]) if raw.get("pending_promotion_symbol") else None,
        )

    @property
    def progress_label(self) -> str:
        target = self.target_promotion_ready_candidates
        if target is None:
            return f"{self.current_promotion_ready_candidates}/미지정"
        return f"{self.current_promotion_ready_candidates}/{target}"

    @property
    def scope_label(self) -> str:
        if self.universe_scope is MissionUniverseScope.MARKET_WIDE:
            return f"{self.market} / {'+'.join(self.exchanges) or '전체'}"
        if self.universe_scope is MissionUniverseScope.SELECTED_SYMBOLS:
            return f"{self.market} / {', '.join(self.symbols)}"
        return f"{self.market} / {self.symbols[0] if self.symbols else '단일 종목'}"


def _tuple_of_str(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(item) for item in value if str(item).strip()))


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    return any(token in value for token in tokens)


# ---------------------------------------------------------------------------
# Continuation / research-intent detection
# ---------------------------------------------------------------------------

_GENERIC_CONTINUATION_TOKENS: tuple[str, ...] = (
    "계속연구",
    "계속해서연구",
    "계속해주세요",
    "계속해줘",
    "증거가충분",
    "충분할때까지",
    "충분한증거",
    "멈추지말고",
    "포기하지말고",
    "승격가능한",
    "승격가능",
    "승격요청이가능",
    "승격할수있는",
    "더연구",
    "이어서연구",
    "이어서",
    "끝까지연구",
    "계속진행",
    "계속진행해",
    "나올때까지",
)

_RESEARCH_VERB_TOKENS: tuple[str, ...] = (
    "연구해주세요",
    "연구해줘",
    "연구해달라",
    "연구해줄래",
    "연구해줄레",
    "연구부탁",
    "연구진행",
)


def is_generic_continuation_request(text: str) -> bool:
    """True for phrasing like "증거가 충분할 때까지 연구해주세요" that asks
    Gaon to keep researching without itself declaring a new scope.

    This is a scope-regression *guard* predicate only - callers must never
    use a positive match here to invent a new mission scope, only to decide
    whether an *existing* mission's scope should be preserved untouched.
    """
    normalized = _norm(text)
    if not normalized:
        return False
    return _contains_any(normalized, _GENERIC_CONTINUATION_TOKENS)


def _mentions_research_verb(normalized: str) -> bool:
    return _contains_any(normalized, _RESEARCH_VERB_TOKENS) or "연구" in normalized


# ---------------------------------------------------------------------------
# Target candidate count extraction
# ---------------------------------------------------------------------------

_KOREAN_DIGIT_WORDS: Mapping[str, int] = {
    "한": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}

_TARGET_COUNT_UNIT_TOKENS: tuple[str, ...] = ("전략", "후보", "종목", "candidate", "strategy")


def _extract_target_count(text: str) -> int | None:
    normalized = _norm(text)
    if not normalized:
        return None
    if not _contains_any(normalized, _TARGET_COUNT_UNIT_TOKENS + ("개",)):
        return None
    digit_match = re.search(r"(\d{1,2})개", normalized)
    if digit_match:
        return int(digit_match.group(1))
    for word, value in _KOREAN_DIGIT_WORDS.items():
        if f"{word}개" in normalized:
            return value
    return None


# ---------------------------------------------------------------------------
# Objective extraction
# ---------------------------------------------------------------------------

_RETURN_TOKENS: tuple[str, ...] = ("수익", "수익률", "return", "profit")
_SAFETY_TOKENS: tuple[str, ...] = ("안전", "안전성", "위험", "리스크", "risk", "mdd", "손실")
_BASELINE_TOKENS: tuple[str, ...] = ("기존전략", "등록되어있는전략", "등록된전략", "현재전략", "챔피언전략", "기존보다", "전략보다")


def _extract_objective(text: str) -> dict[str, object]:
    normalized = _norm(text)
    improve_return = _contains_any(normalized, _RETURN_TOKENS)
    improve_safety = _contains_any(normalized, _SAFETY_TOKENS)
    baseline_comparison = "registered_strategy" if _contains_any(normalized, _BASELINE_TOKENS) else None
    return {
        "improve_return": improve_return,
        "improve_safety": improve_safety,
        "baseline_comparison": baseline_comparison,
    }


_STRATEGY_FAMILY_TOKENS: Mapping[str, tuple[str, ...]] = {
    "short_term_daytrade": ("단타", "데이트레이딩", "스캘핑", "daytrade", "day-trade", "scalping"),
    "swing": ("스윙", "swing"),
    "trend_following": ("추세추종", "trendfollowing"),
}


def _extract_strategy_family(text: str) -> str | None:
    normalized = _norm(text)
    for family, tokens in _STRATEGY_FAMILY_TOKENS.items():
        if _contains_any(normalized, tokens):
            return family
    return None


# ---------------------------------------------------------------------------
# Scope extraction (reuses gaon.research.global_market, no re-implementation)
# ---------------------------------------------------------------------------

_KNOWN_KR_SYMBOL_ALIASES: Mapping[str, str] = {
    "삼성전자": "005930",
    "005930": "005930",
    "sk하이닉스": "000660",
    "하이닉스": "000660",
    "000660": "000660",
    "현대차": "005380",
    "005380": "005380",
    "naver": "035420",
    "네이버": "035420",
    "035420": "035420",
    "lg화학": "051910",
    "051910": "051910",
}


def _extract_explicit_multi_symbols(text: str) -> tuple[str, ...]:
    normalized = _norm(text)
    found: list[str] = []
    for alias, code in _KNOWN_KR_SYMBOL_ALIASES.items():
        if alias in normalized and code not in found:
            found.append(code)
    return tuple(found)


def _kr_market_wide_requested(text: str) -> tuple[bool, tuple[str, ...]]:
    """Reuses ``gaon.research.global_market.resolve_market_scope`` - the same
    scope resolver already trusted by ``multi_symbol_research`` and the
    deterministic tool router - instead of re-implementing scope keyword
    matching here."""
    from gaon.research.global_market import resolve_market_scope

    scope = resolve_market_scope(text)
    if scope is None or scope.market != "KR" or not scope.universe_requested:
        return False, DEFAULT_KR_EXCHANGES
    exchanges = scope.exchanges or DEFAULT_KR_EXCHANGES
    return True, exchanges


# ---------------------------------------------------------------------------
# Mission extraction / update
# ---------------------------------------------------------------------------

def extract_or_update_mission(
    text: str,
    *,
    existing: ResearchMission | None,
    now: str,
) -> ResearchMission | None:
    """Extract a new mission or update an existing one from one user turn.

    Mandatory scope-regression rule: if ``existing`` already has a
    non-single-symbol scope (``selected_symbols`` / ``market_wide``) and this
    turn does not itself declare a new, different scope, the returned
    mission keeps the existing scope untouched. A single-symbol scope is
    only ever produced when the user explicitly names exactly one symbol and
    there is no broader active mission already in place.
    """
    kr_market_wide, exchanges = _kr_market_wide_requested(text)
    explicit_symbols = _extract_explicit_multi_symbols(text)
    target = _extract_target_count(text)
    objective = _extract_objective(text)
    strategy_family = _extract_strategy_family(text)
    normalized = _norm(text)
    continuation = is_generic_continuation_request(text)
    research_intent = (
        kr_market_wide
        or len(explicit_symbols) >= 2
        or target is not None
        or continuation
        or (_mentions_research_verb(normalized) and (objective["improve_return"] or objective["improve_safety"] or strategy_family is not None))
    )

    if existing is None and not research_intent:
        return None

    if kr_market_wide:
        universe_scope = MissionUniverseScope.MARKET_WIDE
        symbols: tuple[str, ...] = ()
        mission_exchanges = exchanges
    elif len(explicit_symbols) >= 2:
        universe_scope = MissionUniverseScope.SELECTED_SYMBOLS
        symbols = explicit_symbols
        mission_exchanges = existing.exchanges if existing is not None else DEFAULT_KR_EXCHANGES
    elif existing is not None:
        # Scope-regression guard: nothing in this turn redefines scope, so
        # the mission's established universe_scope/symbols/exchanges carry
        # forward unchanged, no matter how generically this turn is phrased.
        universe_scope = existing.universe_scope
        symbols = existing.symbols
        mission_exchanges = existing.exchanges
    else:
        universe_scope = MissionUniverseScope.SINGLE_SYMBOL
        symbols = explicit_symbols
        mission_exchanges = DEFAULT_KR_EXCHANGES

    market = "KR" if (kr_market_wide or (existing is not None and existing.market == "KR") or _norm(text).find("한국") >= 0 or _norm(text).find("국내") >= 0 or _norm(text).find("대한민국") >= 0) else (existing.market if existing is not None else "KR")

    merged_target = target if target is not None else (existing.target_promotion_ready_candidates if existing is not None else None)
    merged_return = objective["improve_return"] or (existing.improve_return if existing is not None else False)
    merged_safety = objective["improve_safety"] or (existing.improve_safety if existing is not None else False)
    merged_baseline = objective["baseline_comparison"] or (existing.baseline_comparison if existing is not None else None)
    merged_family = strategy_family or (existing.strategy_family if existing is not None else None)

    if existing is not None:
        status = existing.status
        if status in (MissionStatus.BLOCKED,) and (kr_market_wide or len(explicit_symbols) >= 2 or continuation):
            # A fresh instruction (explicit rescoping or an explicit request
            # to keep going) reactivates a mission that was only blocked by a
            # transient acquisition gap, without touching the promotion
            # target or accumulated evidence.
            status = MissionStatus.ACTIVE
        return replace(
            existing,
            market=market,
            universe_scope=universe_scope,
            symbols=symbols or existing.symbols,
            exchanges=mission_exchanges,
            strategy_family=merged_family,
            improve_return=merged_return,
            improve_safety=merged_safety,
            baseline_comparison=merged_baseline,
            target_promotion_ready_candidates=merged_target,
            status=status,
            updated_at=now,
        )

    return ResearchMission(
        mission_id=f"research-mission:{uuid4().hex}",
        market=market,
        universe_scope=universe_scope,
        symbols=symbols,
        exchanges=mission_exchanges,
        strategy_family=merged_family,
        improve_return=merged_return,
        improve_safety=merged_safety,
        baseline_comparison=merged_baseline,
        target_promotion_ready_candidates=merged_target,
        current_promotion_ready_candidates=0,
        promotion_ready_candidates=(),
        explored_symbols=(),
        status=MissionStatus.ACTIVE,
        blocked_reason=None,
        cycles_completed=0,
        created_at=now,
        updated_at=now,
        originating_request=text,
    )


# ---------------------------------------------------------------------------
# Mission-driven research cycle bookkeeping
# ---------------------------------------------------------------------------

def next_unexplored_symbols(mission: ResearchMission, *, batch_size: int = 5) -> tuple[str, ...]:
    """Only meaningful for ``selected_symbols`` missions: ``market_wide``
    missions let ``multi_symbol_research_payload`` pick its own bounded
    sample every cycle (see ``mission_cycle_request_text``), since that is
    the existing production universe-selection mechanism and this module
    must not re-implement it."""
    remaining = tuple(symbol for symbol in mission.symbols if symbol not in mission.explored_symbols)
    return remaining[:batch_size] if remaining else ()


def mission_cycle_request_text(mission: ResearchMission, request_text: str | None = None) -> str:
    """Builds request text for the next bounded research cycle that keeps
    ``resolve_market_scope`` matching the mission's established scope (KR +
    universe-requested tokens) every cycle, while varying deterministically
    per cycle so ``multi_symbol_research``'s existing seeded universe
    selection samples a different slice of the market each time instead of
    repeating the same symbols."""
    if mission.universe_scope is MissionUniverseScope.MARKET_WIDE:
        exchanges_label = "코스피 코스닥" if set(mission.exchanges) >= {"KOSPI", "KOSDAQ"} else "/".join(mission.exchanges)
        family_label = {"short_term_daytrade": "단타", "swing": "스윙", "trend_following": "추세추종"}.get(mission.strategy_family or "", "")
        return (
            f"국내 주식 {exchanges_label} 전체를 대상으로 {family_label} 전략을 연구해줘 "
            f"(research-mission:{mission.mission_id}:cycle:{mission.cycles_completed + 1})"
        )
    return request_text or mission.originating_request


def record_cycle_result(
    mission: ResearchMission,
    *,
    researched_symbols: tuple[str, ...],
    now: str,
) -> ResearchMission:
    """Records that a bounded research cycle explored the given symbols.

    Budget exhaustion within one cycle is deliberately NOT treated as
    mission completion: the mission stays ``active`` (unless a caller
    separately reports a hard blocker via ``record_blocked``/
    ``record_promotion_candidate``), and the next cycle continues from the
    still-unexplored part of the universe.
    """
    explored = tuple(dict.fromkeys((*mission.explored_symbols, *researched_symbols)))
    return replace(
        mission,
        explored_symbols=explored,
        cycles_completed=mission.cycles_completed + 1,
        updated_at=now,
    )


def record_promotion_candidate(
    mission: ResearchMission,
    *,
    symbol: str,
    run_id: str,
    now: str,
) -> ResearchMission:
    """Records a candidate that the EXISTING PromotionCandidateGate already
    marked ``requires_human_approval`` (see
    ``telegram_autonomous_learning.production_autonomous_learning_payload_from_baseline``).
    Never invents promotion-readiness itself."""
    already_recorded = any(str(item.get("symbol")) == symbol and str(item.get("run_id")) == run_id for item in mission.promotion_ready_candidates)
    if already_recorded:
        return mission
    candidates = (*mission.promotion_ready_candidates, {"symbol": symbol, "run_id": run_id, "detected_at": now})
    count = len(candidates)
    status = mission.status
    target = mission.target_promotion_ready_candidates
    if target is not None and count >= target:
        status = MissionStatus.AWAITING_HUMAN_APPROVAL
    return replace(
        mission,
        promotion_ready_candidates=candidates,
        current_promotion_ready_candidates=count,
        status=status,
        updated_at=now,
    )


def record_focus_symbol(mission: ResearchMission, *, symbol: str, now: str) -> ResearchMission:
    """Marks ``symbol`` (the strongest signal from the most recent
    multi-symbol coverage cycle) as the next cycle's target for the full
    single-candidate Research Director pipeline (OOS/walk-forward/regime/
    cost/Monte Carlo), which is the only pipeline that can actually produce
    a ``request_human_promotion_review`` decision. This keeps each turn to
    exactly one bounded tool call - coverage and per-candidate validation
    alternate across turns instead of both running in the same request."""
    if symbol in {item.get("symbol") for item in mission.promotion_ready_candidates}:
        return mission
    return replace(mission, pending_promotion_symbol=symbol, updated_at=now)


def clear_focus_symbol(mission: ResearchMission, *, now: str) -> ResearchMission:
    return replace(mission, pending_promotion_symbol=None, updated_at=now)


def best_symbol_from_multi_symbol_output(output: Mapping[str, object]) -> str | None:
    """Reads the best-performing symbol the EXISTING ``multi_symbol_research``
    aggregation already identified (``summary.best_symbol``) - does not
    recompute or second-guess that ranking."""
    summary = output.get("summary")
    if not isinstance(summary, Mapping):
        return None
    best = summary.get("best_symbol")
    return str(best) if best else None


def record_blocked(mission: ResearchMission, *, reason: str, now: str) -> ResearchMission:
    """Marks the mission blocked by a legitimate hard blocker (provider
    unavailable, dataset unavailable, no further independent evidence
    source, ...). The mission stays explicit rather than silently
    disappearing; the caller is expected to surface ``blocked_reason`` to
    the user."""
    return replace(mission, status=MissionStatus.BLOCKED, blocked_reason=reason, updated_at=now)


def is_cycle_budget_exhausted(output: Mapping[str, object]) -> bool:
    """True when the EXISTING ``multi_symbol_research`` adaptive-sampling
    budget was fully used within this one call (``adaptive_sampling.
    stop_reason == "research_budget_exhausted"``). This is a within-one-
    request bound, never mission completion - see ``record_cycle_result``."""
    sampling = output.get("adaptive_sampling")
    if not isinstance(sampling, Mapping):
        return False
    return str(sampling.get("stop_reason", "")) == "research_budget_exhausted"


def is_provider_acquisition_blocker(exclusion_diagnostics: Mapping[str, object]) -> bool:
    """True when most/all symbols in a research cycle failed for
    provider/data-acquisition reasons (timeouts, fetch failures, mapping
    failures) rather than because the pipeline evaluated the strategy and
    found it wanting. Callers must treat this as an evidence-acquisition
    blocker, not a negative strategy-validation signal."""
    total = int(exclusion_diagnostics.get("total_excluded", 0) or 0)
    if total <= 0:
        return False
    provider_related = int(exclusion_diagnostics.get("provider_related_excluded", 0) or 0)
    return provider_related > 0 and provider_related >= total


# ---------------------------------------------------------------------------
# User-facing Korean rendering
# ---------------------------------------------------------------------------

def mission_status_block(mission: ResearchMission) -> str:
    return "\n".join(
        [
            "Research Mission",
            f"{mission.scope_label}" + (f" / {_family_label(mission.strategy_family)}" if mission.strategy_family else ""),
            f"promotion-ready candidates: {mission.progress_label}",
        ]
    )


def _family_label(strategy_family: str | None) -> str:
    return {"short_term_daytrade": "단타", "swing": "스윙", "trend_following": "추세추종"}.get(strategy_family or "", strategy_family or "")


def mission_budget_exhausted_message(mission: ResearchMission) -> str:
    lines = [
        "영하님, 연구 목표는 계속 유지하고 있습니다.",
        "",
        "현재 목표:",
        f"- {'국내 전체 주식' if mission.universe_scope is MissionUniverseScope.MARKET_WIDE else mission.scope_label}",
    ]
    if mission.strategy_family:
        lines.append(f"- {_family_label(mission.strategy_family)} 전략")
    if mission.improve_return or mission.improve_safety:
        lines.append("- 기존 전략보다 수익/안전성 개선")
    if mission.target_promotion_ready_candidates is not None:
        lines.append(f"- promotion-ready 후보 {mission.target_promotion_ready_candidates}개")
        lines.append(f"- 현재 {mission.progress_label}")
    lines.extend(
        [
            "",
            "이번 연구 사이클의 adaptive budget을 모두 사용해",
            "같은 요청 안에서 추가 실행은 안전하게 중단했습니다.",
            "",
            "연구 Mission은 종료되지 않았습니다.",
            "다음 연구 사이클에서는 아직 검증하지 않은 종목/전략 후보부터",
            "이어갈 수 있습니다.",
        ]
    )
    return "\n".join(lines)


def mission_blocked_message(mission: ResearchMission) -> str:
    lines = [
        "영하님, 연구 목표는 계속 유지하고 있습니다.",
        "",
        mission_status_block(mission),
        "",
        f"다만 다음 이유로 지금은 안전하게 추가 연구를 진행할 수 없습니다: {mission.blocked_reason or '알 수 없는 차단 사유'}.",
        "임의로 결과를 만들지 않고, 연구가 다시 가능해지면 이어서 진행하겠습니다.",
    ]
    return "\n".join(lines)


def mission_awaiting_approval_message(mission: ResearchMission) -> str:
    lines = [
        f"영하님, 목표하신 promotion-ready 후보 {mission.target_promotion_ready_candidates}개를 모두 확보했습니다.",
        "",
        mission_status_block(mission),
        "",
        "후보 목록:",
    ]
    for item in mission.promotion_ready_candidates:
        lines.append(f"- {item.get('symbol')} (run_id={item.get('run_id')})")
    lines.extend(
        [
            "",
            "자동으로 승격하지 않았습니다. 승인하실 후보를 알려주시면",
            "기존 human-gated 승격 절차로 진행하겠습니다.",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Release check
# ---------------------------------------------------------------------------

def production_persistent_research_mission_release_check() -> Mapping[str, object]:
    """Deterministic, network-free release check for Patch 8.1.

    Exercises mission creation from the real user conversation's wording,
    explicit market-wide scope establishment, the mandatory scope-regression
    guard (a generic continuation message must not narrow a market-wide
    mission back to a single symbol), persistence of the target
    promotion-ready candidate count, budget-exhaustion-is-not-mission-
    completion semantics, bounded per-turn execution, and that reaching the
    target candidate count only ever requests human approval - it never
    auto-promotes.
    """
    now1 = "2026-08-17T00:00:00Z"
    mission = extract_or_update_mission(
        "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. "
        "현재 등록되어있는 전략보다 수익면에서나 안전성 면에서 뛰어나야합니다.",
        existing=None,
        now=now1,
    )
    mission_created = mission is not None

    now2 = "2026-08-17T00:01:00Z"
    mission = extract_or_update_mission("삼성전자말고 국내 주식 전체를 대상으로 연구해주세요", existing=mission, now=now2)
    market_wide_scope_preserved = (
        mission is not None
        and mission.universe_scope is MissionUniverseScope.MARKET_WIDE
        and mission.market == "KR"
    )

    now3 = "2026-08-17T00:02:00Z"
    mission = extract_or_update_mission(
        "승격 요청이 가능한 정도까지 되는 3개의 전략이 나올때까지 연구해주세요 "
        "삼성만 하지말고 국내 주식 전체를 대상으로 연구해주세요",
        existing=mission,
        now=now3,
    )
    target_candidates = mission.target_promotion_ready_candidates if mission is not None else None

    now4 = "2026-08-17T00:03:00Z"
    continued = extract_or_update_mission("증거가 충분할 때까지 멈추지 말고 연구해주세요", existing=mission, now=now4)
    scope_regression_blocked = (
        continued is not None
        and continued.universe_scope is MissionUniverseScope.MARKET_WIDE
        and continued.market == "KR"
        and set(continued.exchanges) >= {"KOSPI", "KOSDAQ"}
    )
    market_scope_preserved = continued is not None and continued.market == "KR"

    exhausted_output = {"adaptive_sampling": {"stop_reason": "research_budget_exhausted"}}
    sufficient_output = {"adaptive_sampling": {"stop_reason": "initial_sample_sufficient"}}
    after_cycle = record_cycle_result(continued, researched_symbols=("005930", "000660"), now=now4)
    budget_exhaustion_not_terminal = (
        is_cycle_budget_exhausted(exhausted_output)
        and not is_cycle_budget_exhausted(sufficient_output)
        and after_cycle.status is MissionStatus.ACTIVE
        and after_cycle.cycles_completed == continued.cycles_completed + 1
    )

    with_focus = record_focus_symbol(after_cycle, symbol="000660", now=now4)
    cleared = clear_focus_symbol(with_focus, now=now4)
    bounded_execution_preserved = with_focus.pending_promotion_symbol == "000660" and cleared.pending_promotion_symbol is None

    with_candidate_1 = record_promotion_candidate(cleared, symbol="005930", run_id="run:1", now=now4)
    with_candidate_2 = record_promotion_candidate(with_candidate_1, symbol="000660", run_id="run:2", now=now4)
    below_target_stays_active = with_candidate_2.status is MissionStatus.ACTIVE
    with_candidate_3 = record_promotion_candidate(with_candidate_2, symbol="005380", run_id="run:3", now=now4)
    human_promotion_gate_preserved = (
        with_candidate_3.current_promotion_ready_candidates == 3
        and with_candidate_3.status is MissionStatus.AWAITING_HUMAN_APPROVAL
        and below_target_stays_active
    )

    checks = {
        "mission_created": mission_created,
        "market_scope_preserved": market_scope_preserved,
        "market_wide_scope_preserved": market_wide_scope_preserved,
        "target_candidates_is_three": target_candidates == 3,
        "scope_regression_blocked": scope_regression_blocked,
        "budget_exhaustion_not_terminal": budget_exhaustion_not_terminal,
        "bounded_execution_preserved": bounded_execution_preserved,
        "human_promotion_gate_preserved": human_promotion_gate_preserved,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"persistent research mission release check failed: {failed}")

    return {
        "schema_version": RESEARCH_MISSION_SCHEMA_VERSION,
        "mission_created": mission_created,
        "market_scope_preserved": market_scope_preserved,
        "market_wide_scope_preserved": market_wide_scope_preserved,
        "target_candidates": target_candidates,
        "scope_regression_blocked": scope_regression_blocked,
        "budget_exhaustion_not_terminal": budget_exhaustion_not_terminal,
        "bounded_execution_preserved": bounded_execution_preserved,
        "human_promotion_gate_preserved": human_promotion_gate_preserved,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }
