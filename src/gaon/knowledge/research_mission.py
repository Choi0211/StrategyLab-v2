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

from gaon.knowledge.strategy_candidate import StrategyCandidateRecord

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
    candidates: tuple[Mapping[str, object], ...] = ()
    active_candidate_id: str | None = None
    candidate_sequence: int = 0

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
            "candidates": [dict(item) for item in self.candidates],
            "active_candidate_id": self.active_candidate_id,
            "candidate_sequence": self.candidate_sequence,
        }

    @staticmethod
    def from_json(raw: Mapping[str, object]) -> "ResearchMission":
        objective = raw.get("objective") if isinstance(raw.get("objective"), Mapping) else {}
        raw_candidates = tuple(dict(item) for item in raw.get("candidates", ()) or () if isinstance(item, Mapping))
        raw_promotion_ready = tuple(dict(item) for item in raw.get("promotion_ready_candidates", ()) if isinstance(item, Mapping))
        # Patch 8.1 -> 8.2 migration (ULTRAREVIEW High #3 fix): a legacy
        # Patch 8.1 entry is shaped {"symbol", "run_id"} with no verified
        # strategy_fingerprint - it cannot be attributed to a distinct
        # strategy identity and must never count toward (or silently
        # inflate) the Patch 8.2 distinct-strategy target. Only entries
        # carrying a real strategy_fingerprint survive; the distinct count
        # of THOSE fingerprints is the single authoritative source for
        # current_promotion_ready_candidates, never the raw persisted
        # number and never raw list length.
        verified_promotion_ready = tuple(
            item for item in raw_promotion_ready if str(item.get("strategy_fingerprint") or "").strip()
        )
        distinct_verified_fingerprints = {str(item["strategy_fingerprint"]) for item in verified_promotion_ready}
        # A legacy pending_promotion_symbol predates the Patch 8.2 candidate
        # portfolio entirely - trusting it for a mission with no persisted
        # candidates would let a brand-new, zero-evidence candidate skip
        # straight to deep validation without ever passing the breadth-
        # sufficiency bar. Only carried forward when a candidate portfolio
        # already exists to anchor it.
        raw_pending_symbol = raw.get("pending_promotion_symbol")
        pending_promotion_symbol = str(raw_pending_symbol) if raw_pending_symbol and raw_candidates else None
        target_promotion_ready_candidates = int(raw["target_promotion_ready_candidates"]) if raw.get("target_promotion_ready_candidates") is not None else None
        raw_status = MissionStatus(str(raw.get("status", MissionStatus.ACTIVE.value)))
        target_reached_by_verified_count = (
            target_promotion_ready_candidates is not None
            and len(distinct_verified_fingerprints) >= target_promotion_ready_candidates
        )
        if raw_status is MissionStatus.AWAITING_HUMAN_APPROVAL and not target_reached_by_verified_count:
            # A legacy mission's persisted status may have reached this
            # state under the old (raw list length) counting rule - only
            # the distinct verified strategy count may authorize it now.
            status = MissionStatus.ACTIVE
        else:
            status = raw_status
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
            target_promotion_ready_candidates=target_promotion_ready_candidates,
            current_promotion_ready_candidates=len(distinct_verified_fingerprints),
            promotion_ready_candidates=verified_promotion_ready,
            explored_symbols=_tuple_of_str(raw.get("explored_symbols")),
            status=status,
            blocked_reason=str(raw["blocked_reason"]) if raw.get("blocked_reason") else None,
            cycles_completed=int(raw.get("cycles_completed", 0) or 0),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            originating_request=str(raw.get("originating_request", "")),
            pending_promotion_symbol=pending_promotion_symbol,
            candidates=raw_candidates,
            active_candidate_id=str(raw["active_candidate_id"]) if raw.get("active_candidate_id") else None,
            candidate_sequence=int(raw.get("candidate_sequence", 0) or 0),
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

# ULTRAREVIEW H3 fix: bare "이어서" and "승격가능"/"승격가능한" used to match
# ANY message containing those substrings, including ordinary explain/show
# follow-ups ("이어서 설명해주세요", "승격 가능한 후보 보여줘") that have
# nothing to do with continuing research. Every token below requires the
# actual research-continuation phrase, not just a loosely related word.
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
    "승격요청이가능",
    "승격할수있는",
    "더연구",
    "이어서연구",
    "이어서진행",
    "이어서계속",
    "끝까지연구",
    "계속진행",
    "계속진행해",
    "나올때까지",
    "다음연구사이클",
    "다음사이클진행",
    "다음단계연구",
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

# Patch 8.2: "다른 방식도 찾아봐" ("look for a different approach too") asks
# Gaon to keep researching within the SAME mission but bias the next
# strategy-hypothesis cycle toward a different candidate family - see
# gaon.runtime.llm_conversation._try_mission_driven_research_cycle's use of
# is_diversity_request to force-rotate an active (non-stagnant) candidate.
_DIVERSITY_REQUEST_TOKENS: tuple[str, ...] = (
    "다른방식",
    "다른전략",
    "다른방법",
    "다른후보",
    "다른접근",
    "새로운전략",
    "새로운방식",
)

# Patch 8.3 production bug fix: "서로 다른 전략 3개가 준비될 때까지" (real
# user wording for the promotion-ready TARGET count - "until 3 mutually
# DISTINCT strategies are ready") contains the bare substring "다른전략",
# which used to be misread by is_diversity_request as a request to abandon
# the currently active candidate and rotate to a new one - discarding real
# in-progress robustness work on every turn that mentioned the target
# count this way. A "다른 전략/방식/방법/후보/접근" phrase followed by a
# count is only excluded when the sentence is ALSO framed as a goal to
# keep working toward ("...때까지" - "until ..."), not a bare digit+개 on
# its own: "다른 전략 2개 더 찾아봐" (find 2 more DIFFERENT strategies -
# an immediate rotation request that happens to state a quantity) must
# still be recognized as diversity/rotation, while "...3개가 준비될
# 때까지"/"...3개가 나올 때까지" (a target-count GOAL, not an immediate
# rotation ask) must not be (ULTRAREVIEW fix: an earlier, broader
# bare-digit exclusion silently suppressed the former).
_DIVERSITY_TARGET_COUNT_MARKER = re.compile(r"다른(?:전략|방식|방법|후보|접근)\d+개")


def is_diversity_request(text: str) -> bool:
    """True for "다른 방식도 찾아봐" style requests to bias the next
    strategy-hypothesis cycle toward a different candidate family, without
    abandoning the mission itself."""
    normalized = _norm(text)
    if not normalized:
        return False
    if _DIVERSITY_TARGET_COUNT_MARKER.search(normalized) and "때까지" in normalized:
        return False
    return _contains_any(normalized, _DIVERSITY_REQUEST_TOKENS)


# Patch 8.3 production bug fix (root cause): a real Telegram conversation
# established a market-wide strategy-centric mission with a promising
# candidate, then asked to continue its robustness validation with phrasing
# like "후보 A 계속 검증해줘" / "OOS 검증해줘" / "walk-forward까지
# 진행해줘". None of these match _GENERIC_CONTINUATION_TOKENS (which only
# recognizes "계속" paired with "연구"/"해주세요"/"해줘"/"진행", never with
# "검증", and never a bare validation-stage name on its own) - so
# gaon.runtime.llm_conversation._try_conversational_mvp's mission-routing-
# precedence hook never fired, and the message fell through to the legacy
# single-symbol autonomous-research path, which resolved its target symbol
# from STALE conversational context (last_symbols[0]) - reproducing the
# exact "resumed an old Samsung Electronics session" defect. These two
# token sets close that gap: an explicit reference to a strategy candidate,
# or a named robustness-validation stage (OOS/walk-forward/regime/
# transaction-cost/Monte Carlo), paired with a request/continue verb, is
# unambiguously a request to continue the active strategy candidate's
# validation - never a reason to invent a new mission scope (same
# scope-regression-guard-only contract as is_generic_continuation_request).
_CANDIDATE_REFERENCE_TOKENS: tuple[str, ...] = ("후보",)
_ROBUSTNESS_STAGE_TOKENS: tuple[str, ...] = (
    "oos",
    "outofsample",
    "워크포워드",
    "walkforward",
    "거래비용",
    "transactioncost",
    "몬테카를로",
    "montecarlo",
    "시장국면",
    "레짐",
    "regime",
    "파라미터민감도",
    "robustness",
)
_CANDIDATE_CONTINUATION_VERB_TOKENS: tuple[str, ...] = (
    "검증해줘",
    "검증해주세요",
    "검증해달라",
    "검증부탁",
    "진행해줘",
    "진행해주세요",
    "진행해달라",
    "계속검증",
    "계속진행",
    "계속해줘",
    "계속해주세요",
)


def is_candidate_robustness_continuation_request(text: str) -> bool:
    """True for "후보 A 계속 검증해줘" / "OOS 검증해줘" / "walk-forward까지
    진행해줘" style requests to continue the ACTIVE strategy candidate's
    robustness validation - see the module-level note above for the
    production defect this closes."""
    normalized = _norm(text)
    if not normalized:
        return False
    mentions_candidate_or_stage = _contains_any(normalized, _CANDIDATE_REFERENCE_TOKENS) or _contains_any(
        normalized, _ROBUSTNESS_STAGE_TOKENS
    )
    return mentions_candidate_or_stage and _contains_any(normalized, _CANDIDATE_CONTINUATION_VERB_TOKENS)


def is_generic_continuation_request(text: str) -> bool:
    """True for phrasing like "증거가 충분할 때까지 연구해주세요" that asks
    Gaon to keep researching without itself declaring a new scope.

    This is a scope-regression *guard* predicate only - callers must never
    use a positive match here to invent a new mission scope, only to decide
    whether an *existing* mission's scope should be preserved untouched.
    Callers with access to the conversational route/intent classifier
    (``gaon.runtime.conversational_mvp.classify_conversational_route``)
    MUST additionally check that the message was not already recognized as
    an explain/detail/risk/recommendation/rerun/timeframe/status follow-up
    before treating a match here as a mission continuation - this predicate
    alone only judges the presence of a research-continuation phrase, not
    the full conversational intent.
    """
    normalized = _norm(text)
    if not normalized:
        return False
    if normalized == "계속":
        # A message that is *only* "계속" ("continue") and nothing else -
        # broader substring matching on bare "계속" would also fire inside
        # unrelated sentences ("계속 지켜보고 있어요"), so this is an exact
        # match, not a substring one.
        return True
    if is_diversity_request(text):
        # "다른 방식도 찾아봐" asks Gaon to keep researching (within the
        # same mission) with a different strategy hypothesis - a request to
        # continue, just biased toward diversity.
        return True
    if is_candidate_robustness_continuation_request(text):
        return True
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
    """Extracts a target promotion-ready candidate count like "3개" from
    ``text``. Explicitly excludes duration phrases such as "3개월"
    (3 months), "3개년" (3 years) or "3개당" (per 3 units) - "개" immediately
    followed by 월/년/당 is a unit-of-time/rate suffix, never a candidate
    count, and must never be misread as one."""
    normalized = _norm(text)
    if not normalized:
        return None
    if not _contains_any(normalized, _TARGET_COUNT_UNIT_TOKENS + ("개",)):
        return None
    digit_match = re.search(r"(\d{1,2})개(?!월|년|당)", normalized)
    if digit_match:
        return int(digit_match.group(1))
    for word, value in _KOREAN_DIGIT_WORDS.items():
        if re.search(rf"{word}개(?!월|년|당)", normalized):
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
    elif len(explicit_symbols) == 1 and not continuation:
        # Explicit single-symbol override (e.g. "삼성전자만 다시 연구해"):
        # the user named exactly one symbol and this is NOT a generic
        # continuation phrase, so it is treated as a real scope declaration
        # and narrows even an existing broader mission down to that symbol -
        # the scope-regression guard below only ever applies when the turn
        # itself carries no explicit scope signal.
        universe_scope = MissionUniverseScope.SINGLE_SYMBOL
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
    """Builds request text for the next bounded market-wide/multi-symbol
    coverage cycle that keeps ``resolve_market_scope`` matching the
    mission's established scope (KR + universe-requested tokens) every
    cycle, while varying deterministically per cycle so
    ``multi_symbol_research``'s existing seeded universe selection samples a
    different slice of the market each time instead of repeating the same
    symbols.

    This text is only ever consumed by ``multi_symbol_research`` (universe
    selection/strategy parsing), which never sends it to an external
    provider - it must NOT be reused as the ``request_text`` for
    ``autonomous_learning_research``/external-research tool calls (see
    ``mission_promotion_request_text``), since those forward it verbatim as
    an outbound search query and the cycle marker below is internal
    control metadata, not a real query.
    """
    if mission.universe_scope is MissionUniverseScope.MARKET_WIDE:
        exchanges_label = "코스피 코스닥" if set(mission.exchanges) >= {"KOSPI", "KOSDAQ"} else "/".join(mission.exchanges)
        family_label = {"short_term_daytrade": "단타", "swing": "스윙", "trend_following": "추세추종"}.get(mission.strategy_family or "", "")
        return (
            f"국내 주식 {exchanges_label} 전체를 대상으로 {family_label} 전략을 연구해줘 "
            f"({mission.mission_id}:cycle:{mission.cycles_completed + 1})"
        )
    return request_text or mission.originating_request


def mission_promotion_request_text(mission: ResearchMission, symbol: str) -> str:
    """Builds a clean, human-readable request text for validating ONE
    candidate symbol through the single-candidate Autonomous Learning V2 /
    Research Director pipeline.

    Deliberately excludes internal control metadata (mission_id, cycle
    counters) that ``mission_cycle_request_text`` embeds for market-wide
    universe-sampling purposes: this text is forwarded verbatim as the
    external-research search query for every configured provider category
    (see ``telegram_autonomous_learning.py``'s multi-source research
    queries), so it must read as a real research request a human could have
    typed, not as internal bookkeeping.
    """
    family_label = {"short_term_daytrade": "단타", "swing": "스윙", "trend_following": "추세추종"}.get(mission.strategy_family or "", "")
    family_phrase = f"{family_label} " if family_label else ""
    return f"{symbol} {family_phrase}전략을 처음부터 다시 연구해줘. 외부 자료와 실제 시장 데이터를 사용해."


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
    strategy_fingerprint: str,
    candidate_id: str,
    now: str,
) -> ResearchMission:
    """Records a DISTINCT STRATEGY (identified by its symbol-independent
    ``strategy_family_fingerprint``, never by a symbol) that the EXISTING
    PromotionCandidateGate/Research Director pipeline already marked
    ``requires_human_approval`` / ``request_human_promotion_review`` (see
    ``telegram_autonomous_learning.production_autonomous_learning_payload_from_baseline``).
    Never invents promotion-readiness itself.

    Patch 8.2: promotion-ready count is the number of DISTINCT strategy
    fingerprints recorded here, not the number of symbols a strategy was
    evaluated on - running one candidate across 50 symbols still counts as
    one entry; a second candidate must have a genuinely different
    fingerprint (different entry/exit/filter rules) to count as a second.

    ULTRAREVIEW fix: an empty/unverifiable ``strategy_fingerprint`` is
    silently ignored rather than recorded - callers (see
    ``llm_conversation._try_candidate_robustness_cycle``) must only ever
    pass a fingerprint that has been positively confirmed to match what the
    deep-validation stage actually validated. If identity cannot be
    verified, this function must not be called with a real value at all,
    and calling it with an empty one is a safe no-op rather than an error,
    so a caller-side verification gap can never silently inflate the count.
    """
    fingerprint = str(strategy_fingerprint or "").strip()
    if not fingerprint:
        return mission
    already_recorded = any(str(item.get("strategy_fingerprint")) == fingerprint for item in mission.promotion_ready_candidates)
    if already_recorded:
        return mission
    candidates = (*mission.promotion_ready_candidates, {"strategy_fingerprint": fingerprint, "candidate_id": candidate_id, "detected_at": now})
    # The authoritative count is always the number of DISTINCT verified
    # fingerprints in the resulting list, never its raw length - this is
    # the single source of truth the AWAITING_HUMAN_APPROVAL transition
    # below relies on (mirrors distinct_promotion_ready_strategy_count).
    count = len({str(item.get("strategy_fingerprint")) for item in candidates if item.get("strategy_fingerprint")})
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
    """Marks ``symbol`` (evaluation evidence drawn from the ACTIVE strategy
    candidate's own validated universe - see ``get_active_candidate``) as
    the next cycle's target for the single-candidate Research Director
    pipeline (OOS/walk-forward/regime/cost/Monte Carlo), which is the only
    pipeline that can actually produce a ``request_human_promotion_review``
    decision. The symbol is evaluation evidence FOR the active candidate,
    never a new identity - this keeps each turn to exactly one bounded
    tool call - coverage and per-candidate validation alternate across
    turns instead of both running in the same request."""
    return replace(mission, pending_promotion_symbol=symbol, updated_at=now)


def clear_focus_symbol(mission: ResearchMission, *, now: str) -> ResearchMission:
    return replace(mission, pending_promotion_symbol=None, updated_at=now)


# ---------------------------------------------------------------------------
# Patch 8.2 - strategy candidate portfolio
# ---------------------------------------------------------------------------
#
# The mission now manages a PORTFOLIO of gaon.knowledge.strategy_candidate.
# StrategyCandidateRecord entries (JSON-encoded in `candidates`) instead of
# a single symbol. Symbols remain evaluation evidence recorded ON a
# candidate (see StrategyCandidateRecord.evidence_symbols/attempted_symbols/
# valid_symbols) - they are never mission-level identity.

def candidate_records(mission: ResearchMission) -> tuple[StrategyCandidateRecord, ...]:
    return tuple(StrategyCandidateRecord.from_json(item) for item in mission.candidates)


def get_candidate(mission: ResearchMission, candidate_id: str) -> StrategyCandidateRecord | None:
    for candidate in candidate_records(mission):
        if candidate.candidate_id == candidate_id:
            return candidate
    return None


def get_active_candidate(mission: ResearchMission) -> StrategyCandidateRecord | None:
    if mission.active_candidate_id is None:
        return None
    return get_candidate(mission, mission.active_candidate_id)


def add_candidate(mission: ResearchMission, candidate: StrategyCandidateRecord, *, now: str) -> ResearchMission:
    """Appends a newly generated strategy candidate to the mission's
    portfolio and makes it the active one. Never replaces an existing
    candidate with the same id (candidate_id is a stable KR-ST-NNN
    sequence number, generated once per mission via
    ``next_candidate_sequence``)."""
    if get_candidate(mission, candidate.candidate_id) is not None:
        return mission
    return replace(
        mission,
        candidates=(*mission.candidates, candidate.to_json()),
        active_candidate_id=candidate.candidate_id,
        candidate_sequence=max(mission.candidate_sequence, _sequence_from_candidate_id(candidate.candidate_id)),
        updated_at=now,
    )


def update_candidate(mission: ResearchMission, candidate: StrategyCandidateRecord, *, now: str) -> ResearchMission:
    """Replaces the stored record for ``candidate.candidate_id`` with the
    given (already-updated) record. No-op if the candidate is not part of
    this mission's portfolio."""
    updated = []
    found = False
    for item in mission.candidates:
        if str(item.get("candidate_id")) == candidate.candidate_id:
            updated.append(candidate.to_json())
            found = True
        else:
            updated.append(item)
    if not found:
        return mission
    return replace(mission, candidates=tuple(updated), updated_at=now)


def set_active_candidate(mission: ResearchMission, candidate_id: str | None, *, now: str) -> ResearchMission:
    return replace(mission, active_candidate_id=candidate_id, updated_at=now)


def next_candidate_sequence(mission: ResearchMission) -> int:
    return mission.candidate_sequence + 1


def _sequence_from_candidate_id(candidate_id: str) -> int:
    try:
        return int(candidate_id.rsplit("-", 1)[-1])
    except ValueError:
        return 0


def distinct_promotion_ready_strategy_count(mission: ResearchMission) -> int:
    """The authoritative promotion-ready count: the number of DISTINCT
    strategy fingerprints recorded via ``record_promotion_candidate`` -
    running one candidate across many symbols, or holding many
    still-exploring candidates, never inflates this number."""
    return len({str(item.get("strategy_fingerprint")) for item in mission.promotion_ready_candidates if item.get("strategy_fingerprint")})


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
        ]
    )
    # This specific "아직 검증하지 않은 종목부터 이어간다" claim is only
    # actually true for selected_symbols missions, which track
    # explored_symbols and pick unexplored ones next
    # (next_unexplored_symbols). Market-wide missions do not currently
    # exclude already-explored symbols from the next sample, so they get a
    # truthful, non-specific continuation statement instead of a promise
    # this code cannot keep.
    if mission.universe_scope is MissionUniverseScope.SELECTED_SYMBOLS:
        lines.extend(["다음 연구 사이클에서는 아직 검증하지 않은 종목부터 이어갈 수 있습니다."])
    else:
        lines.extend(["다음 연구 사이클에서 계속 진행하겠습니다."])
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
        fingerprint = str(item.get("strategy_fingerprint") or "")
        lines.append(f"- {item.get('candidate_id', '?')} (strategy_fingerprint={fingerprint[:12]})")
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

    with_candidate_1 = record_promotion_candidate(cleared, strategy_fingerprint="fp-aaa", candidate_id="KR-ST-001", now=now4)
    with_candidate_2 = record_promotion_candidate(with_candidate_1, strategy_fingerprint="fp-bbb", candidate_id="KR-ST-002", now=now4)
    below_target_stays_active = with_candidate_2.status is MissionStatus.ACTIVE
    with_candidate_3 = record_promotion_candidate(with_candidate_2, strategy_fingerprint="fp-ccc", candidate_id="KR-ST-003", now=now4)
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


def production_strategy_centric_autonomous_research_release_check() -> Mapping[str, object]:
    """Deterministic, network-free release check for Patch 8.2.

    Exercises: the strategy candidate as the primary research unit,
    symbol-independent candidate fingerprints, cross-symbol evidence
    recording under ONE candidate, the distinct-strategy-fingerprint
    promotion target, stagnation-driven candidate rotation, and that the
    mission's baseline-comparison objective and human promotion gate are
    both preserved unmodified.
    """
    from gaon.knowledge.strategy_candidate import (
        build_candidate_spec,
        is_stagnant,
        mark_stagnant,
        new_candidate,
        next_untried_family,
        record_breadth_progress,
    )

    now1 = "2026-08-17T00:00:00Z"
    mission = extract_or_update_mission(
        "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. "
        "현재 등록되어있는 전략보다 수익면에서나 안전성 면에서 뛰어나야합니다.",
        existing=None,
        now=now1,
    )
    mission = extract_or_update_mission("국내 주식 전체를 대상으로 연구해주세요", existing=mission, now=now1)

    candidate_a = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=now1)
    mission = add_candidate(mission, candidate_a, now=now1)
    strategy_candidate_primary_unit = mission.active_candidate_id == candidate_a.candidate_id and len(mission.candidates) == 1

    spec_a = build_candidate_spec(candidate_a.strategy_family, placeholder_symbol="005930", created_at=now1)
    spec_b = build_candidate_spec(candidate_a.strategy_family, placeholder_symbol="000660", created_at=now1)
    candidate_fingerprint_symbol_independent = (
        spec_a.strategy_family_fingerprint == spec_b.strategy_family_fingerprint == candidate_a.strategy_fingerprint
    )

    now2 = "2026-08-17T00:01:00Z"
    progressed = record_breadth_progress(
        candidate_a,
        attempted=15,
        valid=12,
        trade_count=340,
        evidence_symbols=("005930", "000660", "473050"),
        excluded_symbols=("999999", "999998", "999997"),
        provider_blocked=False,
        now=now2,
    )
    mission = update_candidate(mission, progressed, now=now2)
    cross_symbol_validation = progressed.attempted_symbols == 15 and progressed.valid_symbols == 12 and len(progressed.evidence_symbols) >= 2
    symbols_are_evidence_samples = "473050" in progressed.evidence_symbols
    bounded_execution_preserved = progressed.cycles_completed == 1

    now3 = "2026-08-17T00:02:00Z"
    mission = extract_or_update_mission(
        "승격 요청이 가능한 정도까지 되는 3개의 전략이 나올때까지 연구해주세요",
        existing=mission,
        now=now3,
    )
    mission_scope_preserved = mission.universe_scope is MissionUniverseScope.MARKET_WIDE and mission.market == "KR"
    baseline_comparison_preserved = mission.baseline_comparison == "registered_strategy" and mission.improve_return and mission.improve_safety

    now4 = "2026-08-17T00:03:00Z"
    stagnant_source = progressed
    for _ in range(4):
        stagnant_source = record_breadth_progress(
            stagnant_source, attempted=15, valid=12, trade_count=340,
            evidence_symbols=(), excluded_symbols=(), provider_blocked=False, now=now4,
        )
    candidate_actually_stagnant = is_stagnant(stagnant_source)
    rotated = mark_stagnant(stagnant_source, now=now4)
    next_family = next_untried_family((rotated,))
    stagnation_can_rotate_candidate = (
        candidate_actually_stagnant and next_family is not None and next_family != rotated.strategy_family
    )

    now5 = "2026-08-17T00:04:00Z"
    promoted_once = record_promotion_candidate(mission, strategy_fingerprint=candidate_a.strategy_fingerprint, candidate_id=candidate_a.candidate_id, now=now5)
    promoted_duplicate = record_promotion_candidate(promoted_once, strategy_fingerprint=candidate_a.strategy_fingerprint, candidate_id=candidate_a.candidate_id, now=now5)
    human_promotion_gate_preserved = (
        promoted_duplicate.current_promotion_ready_candidates == 1
        and promoted_duplicate.status is not MissionStatus.AWAITING_HUMAN_APPROVAL
    )

    # ULTRAREVIEW High #3 fix: a Patch 8.1 mission persisted before Patch
    # 8.2 existed may carry promotion_ready_candidates shaped
    # {"symbol", "run_id"} (no strategy_fingerprint) and a stale
    # pending_promotion_symbol with no candidate portfolio behind it -
    # loading it must never let those legacy entries count toward the
    # Patch 8.2 distinct-strategy target, and must never let a fresh
    # candidate skip breadth validation via the stale pending symbol.
    legacy_patch_8_1_mission_raw = {
        "schema_version": 1,
        "mission_id": "research-mission:legacy-8-1",
        "market": "KR",
        "universe_scope": MissionUniverseScope.MARKET_WIDE.value,
        "symbols": [],
        "exchanges": ["KOSPI", "KOSDAQ"],
        "strategy_family": None,
        "objective": {"improve_return": True, "improve_safety": True, "baseline_comparison": "registered_strategy"},
        "target_promotion_ready_candidates": 3,
        "current_promotion_ready_candidates": 3,
        "promotion_ready_candidates": [
            {"symbol": "005930", "run_id": "run-1"},
            {"symbol": "000660", "run_id": "run-2"},
            {"symbol": "473050", "run_id": "run-3"},
        ],
        "explored_symbols": ["005930", "000660", "473050"],
        "status": MissionStatus.AWAITING_HUMAN_APPROVAL.value,
        "blocked_reason": None,
        "cycles_completed": 5,
        "created_at": now1,
        "updated_at": now1,
        "originating_request": "국내 주식 전체를 대상으로 연구해주세요",
        "pending_promotion_symbol": "005930",
    }
    legacy_mission = ResearchMission.from_json(legacy_patch_8_1_mission_raw)
    legacy_migration_safe = (
        legacy_mission.current_promotion_ready_candidates == 0
        and legacy_mission.promotion_ready_candidates == ()
        and legacy_mission.status is MissionStatus.ACTIVE
        and legacy_mission.pending_promotion_symbol is None
        and legacy_mission.market == "KR"
        and legacy_mission.universe_scope is MissionUniverseScope.MARKET_WIDE
    )

    checks = {
        "strategy_candidate_primary_unit": strategy_candidate_primary_unit,
        "candidate_fingerprint_symbol_independent": candidate_fingerprint_symbol_independent,
        "cross_symbol_validation": cross_symbol_validation,
        "distinct_strategy_target_is_three": mission.target_promotion_ready_candidates == 3,
        "symbols_are_evidence_samples": symbols_are_evidence_samples,
        "stagnation_can_rotate_candidate": stagnation_can_rotate_candidate,
        "baseline_comparison_preserved": baseline_comparison_preserved,
        "mission_scope_preserved": mission_scope_preserved,
        "bounded_execution_preserved": bounded_execution_preserved,
        "human_promotion_gate_preserved": human_promotion_gate_preserved,
        "legacy_migration_safe": legacy_migration_safe,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"strategy-centric autonomous research release check failed: {failed}")

    return {
        "schema_version": RESEARCH_MISSION_SCHEMA_VERSION,
        "strategy_candidate_primary_unit": strategy_candidate_primary_unit,
        "candidate_fingerprint_symbol_independent": candidate_fingerprint_symbol_independent,
        "cross_symbol_validation": cross_symbol_validation,
        "distinct_strategy_target": mission.target_promotion_ready_candidates,
        "symbols_are_evidence_samples": symbols_are_evidence_samples,
        "stagnation_can_rotate_candidate": stagnation_can_rotate_candidate,
        "baseline_comparison_preserved": baseline_comparison_preserved,
        "mission_scope_preserved": mission_scope_preserved,
        "bounded_execution_preserved": bounded_execution_preserved,
        "human_promotion_gate_preserved": human_promotion_gate_preserved,
        "legacy_migration_safe": legacy_migration_safe,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }


def production_persistent_strategy_candidate_continuation_release_check() -> Mapping[str, object]:
    """Deterministic, network-free release check for Patch 8.3.

    Exercises the production defect this patch fixes: a real Telegram
    conversation established a market-wide strategy-centric mission with a
    promising candidate, then asked to continue that candidate's
    robustness validation with natural phrasing ("후보 A 계속 검증해줘",
    "OOS 검증해줘") that a narrower, hand-enumerated continuation-phrase
    predicate did not recognize - so the message fell through to the
    legacy single-symbol autonomous-research path, which resolved its
    target symbol from STALE conversational context instead of the
    mission's own persisted candidate. Also exercises candidate identity
    persistence across a restart/reload, cross-symbol evidence, candidate
    rotation, distinct promotion-ready counting, and the unchanged human
    promotion gate.
    """
    from gaon.knowledge.strategy_candidate import (
        is_stagnant,
        mark_stagnant,
        new_candidate,
        next_untried_family,
        record_breadth_progress,
        record_robustness_progress,
    )

    now1 = "2026-08-17T00:00:00Z"
    mission = extract_or_update_mission(
        "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. "
        "현재 등록되어있는 전략보다 수익면에서나 안전성 면에서 뛰어나야합니다.",
        existing=None,
        now=now1,
    )
    mission = extract_or_update_mission("국내 주식 전체를 대상으로 연구해주세요", existing=mission, now=now1)

    candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=now1)
    mission = add_candidate(mission, candidate, now=now1)
    fingerprint_before = candidate.strategy_fingerprint

    now2 = "2026-08-17T00:01:00Z"
    progressed = record_breadth_progress(
        candidate,
        attempted=15,
        valid=12,
        trade_count=340,
        evidence_symbols=("005930", "000660", "473050"),
        excluded_symbols=(),
        provider_blocked=False,
        now=now2,
    )
    mission = update_candidate(mission, progressed, now=now2)
    cross_symbol_identity_preserved = (
        progressed.strategy_fingerprint == fingerprint_before
        and progressed.valid_symbols == 12
        and len(progressed.evidence_symbols) >= 2
    )
    strategy_candidate_persisted = (
        len(mission.candidates) == 1
        and mission.active_candidate_id == candidate.candidate_id
        and get_candidate(mission, candidate.candidate_id).evidence_symbols == progressed.evidence_symbols
    )

    # The exact production defect: these real user phrasings must be
    # recognized as a mission continuation (never silently ignored, which
    # is what let a stale single-symbol session resurface in production).
    real_production_continuation_phrases = (
        "후보 A 계속 검증해줘",
        "OOS 검증해줘",
        "walk-forward까지 진행해줘",
        "계속 연구해줘",
        "승격 가능한 전략 3개가 나올 때까지 계속해줘",
    )
    stale_symbol_context_blocked = all(
        is_generic_continuation_request(phrase) for phrase in real_production_continuation_phrases
    )
    # "서로 다른 전략 3개" declares the target count's distinctness - it
    # must never be misread as a request to abandon the active candidate.
    stale_symbol_context_blocked = stale_symbol_context_blocked and not is_diversity_request(
        "서로 다른 전략 3개가 준비될 때까지 연구해주세요"
    )

    now3 = "2026-08-17T00:02:00Z"
    robustness_progressed = record_robustness_progress(progressed, director_action="collect_more_evidence", terminal=False, now=now3)
    candidate_fingerprint_preserved = robustness_progressed.strategy_fingerprint == fingerprint_before
    mission = update_candidate(mission, robustness_progressed, now=now3)

    # Restart/reload: a brand new in-memory reconstruction from the exact
    # persisted JSON (what a real process restart reloads from) must carry
    # the active candidate and its accumulated progress forward unchanged.
    reloaded_mission = ResearchMission.from_json(mission.to_json())
    reloaded_candidate = get_candidate(reloaded_mission, candidate.candidate_id)
    restart_persistence = (
        reloaded_mission.active_candidate_id == candidate.candidate_id
        and reloaded_candidate is not None
        and reloaded_candidate.strategy_fingerprint == fingerprint_before
        and reloaded_candidate.valid_symbols == 12
        and reloaded_candidate.last_director_action == "collect_more_evidence"
    )

    now4 = "2026-08-17T00:03:00Z"
    stagnant_source = robustness_progressed
    for _ in range(4):
        stagnant_source = record_robustness_progress(stagnant_source, director_action="collect_more_evidence", terminal=False, now=now4)
    rotated = mark_stagnant(stagnant_source, now=now4)
    next_family = next_untried_family((rotated,))
    candidate_rotation = is_stagnant(stagnant_source) and next_family is not None and next_family != rotated.strategy_family

    now5 = "2026-08-17T00:04:00Z"
    fp_a, fp_b, fp_c = "fp-continuation-a", "fp-continuation-b", "fp-continuation-c"
    target_mission = extract_or_update_mission(
        "승격 요청이 가능한 정도까지 되는 3개의 전략이 나올때까지 연구해주세요", existing=mission, now=now5
    )
    counted = record_promotion_candidate(target_mission, strategy_fingerprint=fp_a, candidate_id="KR-ST-101", now=now5)
    counted = record_promotion_candidate(counted, strategy_fingerprint=fp_a, candidate_id="KR-ST-101", now=now5)  # duplicate, must not double-count
    below_target_after_duplicate = counted.current_promotion_ready_candidates == 1 and counted.status is MissionStatus.ACTIVE
    counted = record_promotion_candidate(counted, strategy_fingerprint=fp_b, candidate_id="KR-ST-102", now=now5)
    counted = record_promotion_candidate(counted, strategy_fingerprint=fp_c, candidate_id="KR-ST-103", now=now5)
    distinct_promotion_counting = (
        below_target_after_duplicate
        and counted.current_promotion_ready_candidates == 3
        and counted.current_promotion_ready_candidates == distinct_promotion_ready_strategy_count(counted)
        and counted.status is MissionStatus.AWAITING_HUMAN_APPROVAL
    )
    human_promotion_gate_preserved = distinct_promotion_counting

    with_focus = record_focus_symbol(mission, symbol="005930", now=now3)
    cleared = clear_focus_symbol(with_focus, now=now3)
    bounded_execution_preserved = with_focus.pending_promotion_symbol == "005930" and cleared.pending_promotion_symbol is None

    checks = {
        "strategy_candidate_persisted": strategy_candidate_persisted,
        "candidate_fingerprint_preserved": candidate_fingerprint_preserved,
        "stale_symbol_context_blocked": stale_symbol_context_blocked,
        "cross_symbol_identity_preserved": cross_symbol_identity_preserved,
        "candidate_rotation": candidate_rotation,
        "distinct_promotion_counting": distinct_promotion_counting,
        "restart_persistence": restart_persistence,
        "bounded_execution_preserved": bounded_execution_preserved,
        "human_promotion_gate_preserved": human_promotion_gate_preserved,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"persistent strategy candidate continuation release check failed: {failed}")

    return {
        "schema_version": RESEARCH_MISSION_SCHEMA_VERSION,
        "strategy_candidate_persisted": strategy_candidate_persisted,
        "candidate_fingerprint_preserved": candidate_fingerprint_preserved,
        "stale_symbol_context_blocked": stale_symbol_context_blocked,
        "cross_symbol_identity_preserved": cross_symbol_identity_preserved,
        "candidate_rotation": candidate_rotation,
        "distinct_promotion_counting": distinct_promotion_counting,
        "restart_persistence": restart_persistence,
        "bounded_execution_preserved": bounded_execution_preserved,
        "human_promotion_gate_preserved": human_promotion_gate_preserved,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }
