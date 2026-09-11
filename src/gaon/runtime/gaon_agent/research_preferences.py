"""Conversation-scoped research preferences (Gaon roadmap #217 follow-up:
"conversation deepening").

A *preference* here is the user's stated research goal / wish for how a
research mission should be shaped - target market, trading style,
timeframes, an aspirational win rate, an aspirational daily return range.
It is deliberately **not** part of :class:`gaon.knowledge.research_mission.
ResearchMission` - that schema stays exactly as PR #216 left it - and it is
**not** persisted to any database; this module only extracts a structured,
immutable value from one turn's text and renders it back honestly.

The single non-negotiable rule this module exists to enforce: a target win
rate or a daily return range is a *research goal the user hopes for*, never
a guarantee, expectation or promise. ``render_research_preferences_summary``
and :func:`reconcile_with_mission` therefore only ever use "연구 목표" /
"희망 조건" framing and explicitly say returns are not guaranteed - callers
must not build their own competing phrasing for these numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TIMEFRAME_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1m", ("1분", "1 분", "1m", "one minute")),
    ("5m", ("5분", "5 분", "5m")),
    ("15m", ("15분", "15 분", "15m")),
    ("30m", ("30분", "30 분", "30m")),
)

_SHORT_TERM_TOKENS: tuple[str, ...] = ("단타", "데이트레이", "day trade", "daytrade", "intraday", "초단타", "스캘핑")

_KR_MARKET_TOKENS: tuple[str, ...] = ("코스피", "코스닥", "kospi", "kosdaq", "국내 주식", "국내주식", "한국 주식")

_WIN_RATE_RE = re.compile(r"승률[^0-9]{0,6}(\d{1,3})\s*%")
_DAILY_RETURN_RANGE_RE = re.compile(
    r"(?:일|하루)[^0-9]{0,6}(\d{1,3}(?:\.\d+)?)\s*[~\-–]\s*(\d{1,3}(?:\.\d+)?)\s*%"
)
_DAILY_RETURN_SINGLE_RE = re.compile(r"(?:일|하루)[^0-9]{0,6}수익률[^0-9]{0,6}(\d{1,3}(?:\.\d+)?)\s*%")


@dataclass(frozen=True)
class ResearchPreferences:
    """One turn's structured, aspirational research preference.

    Every field is what the user *wants to aim for*, never a fact about the
    world and never a commitment the runtime makes. ``target_win_rate_pct``
    and ``aspirational_daily_return_range_pct`` in particular must only ever
    be shown to the user through :func:`render_research_preferences_summary`
    or :func:`reconcile_with_mission`, which carry the mandatory
    non-guarantee framing.
    """

    market_scope: str | None = None
    trading_style: str | None = None
    timeframes: tuple[str, ...] = ()
    target_win_rate_pct: float | None = None
    aspirational_daily_return_range_pct: tuple[float, float] | None = None

    @property
    def is_empty(self) -> bool:
        return (
            self.market_scope is None
            and self.trading_style is None
            and not self.timeframes
            and self.target_win_rate_pct is None
            and self.aspirational_daily_return_range_pct is None
        )


def mentions_research_preferences(text: str) -> bool:
    """``True`` only when this turn states one of the fields genuinely new
    to this preference model - a timeframe, a win-rate target or a
    daily-return aspiration.

    Deliberately narrower than "any field in :class:`ResearchPreferences` is
    non-empty": ``market_scope`` and ``trading_style`` alone (e.g. "국내
    주식 코스피+코스닥 단타 전략을 연구해주세요") are exactly the wording an
    ordinary new-mission request already uses - if this predicate fired on
    those two fields alone it would hijack mission creation/continuation
    turns into a preference-reconciliation reply instead. Requiring a
    timeframe/win-rate/return field keeps this module strictly additive: it
    only ever engages for a turn that states something a
    :class:`gaon.knowledge.research_mission.ResearchMission` cannot already
    represent."""
    preferences = extract_research_preferences(text)
    return bool(
        preferences.timeframes
        or preferences.target_win_rate_pct is not None
        or preferences.aspirational_daily_return_range_pct is not None
    )


def extract_research_preferences(text: str) -> ResearchPreferences:
    """Parse ``text`` for the fixed, typed set of preference fields this
    module understands. Fields not mentioned are left ``None``/empty -
    this never guesses a value the user did not state."""
    market_scope = "KR_KOSPI_KOSDAQ" if any(token in text.casefold() for token in _KR_MARKET_TOKENS) else None
    trading_style = "short_term_intraday" if any(token in text for token in _SHORT_TERM_TOKENS) else None
    timeframes = tuple(code for code, tokens in _TIMEFRAME_TOKENS if any(token in text.casefold() for token in tokens))

    win_rate_match = _WIN_RATE_RE.search(text)
    target_win_rate = float(win_rate_match.group(1)) if win_rate_match else None

    return_range: tuple[float, float] | None = None
    range_match = _DAILY_RETURN_RANGE_RE.search(text)
    if range_match:
        low, high = sorted((float(range_match.group(1)), float(range_match.group(2))))
        return_range = (low, high)
    elif _DAILY_RETURN_SINGLE_RE.search(text):
        value = float(_DAILY_RETURN_SINGLE_RE.search(text).group(1))
        return_range = (value, value)

    return ResearchPreferences(
        market_scope=market_scope,
        trading_style=trading_style,
        timeframes=timeframes,
        target_win_rate_pct=target_win_rate,
        aspirational_daily_return_range_pct=return_range,
    )


def merge_research_preferences(
    base: ResearchPreferences, update: ResearchPreferences
) -> ResearchPreferences:
    """Immutable merge: a field stated in ``update`` overrides ``base``;
    an unstated field keeps ``base``'s value. Used to fold a newly-stated
    preference field into whatever this conversation already established
    earlier in the same turn/session context, without ever discarding a
    field the user is not currently overriding."""
    return ResearchPreferences(
        market_scope=update.market_scope or base.market_scope,
        trading_style=update.trading_style or base.trading_style,
        timeframes=update.timeframes or base.timeframes,
        target_win_rate_pct=update.target_win_rate_pct if update.target_win_rate_pct is not None else base.target_win_rate_pct,
        aspirational_daily_return_range_pct=(
            update.aspirational_daily_return_range_pct
            if update.aspirational_daily_return_range_pct is not None
            else base.aspirational_daily_return_range_pct
        ),
    )


_MARKET_SCOPE_LABEL = {"KR_KOSPI_KOSDAQ": "국내 주식(코스피+코스닥)"}
_TRADING_STYLE_LABEL = {"short_term_intraday": "단타/단기 매매"}


def render_research_preferences_summary(preferences: ResearchPreferences) -> list[str]:
    """Korean lines describing ``preferences`` - always as a stated wish,
    never as a guarantee. Every caller that shows these numbers to the user
    must go through this function (or :func:`reconcile_with_mission`, which
    calls it) rather than interpolating the raw fields."""
    lines: list[str] = []
    if preferences.market_scope:
        lines.append(f"- 시장 범위: {_MARKET_SCOPE_LABEL.get(preferences.market_scope, preferences.market_scope)}")
    if preferences.trading_style:
        lines.append(f"- 매매 스타일: {_TRADING_STYLE_LABEL.get(preferences.trading_style, preferences.trading_style)}")
    if preferences.timeframes:
        lines.append(f"- 관심 타임프레임: {', '.join(preferences.timeframes)}")
    if preferences.target_win_rate_pct is not None:
        lines.append(f"- 희망 승률(연구 목표): 약 {preferences.target_win_rate_pct:.0f}% (보장이 아닌 목표치)")
    if preferences.aspirational_daily_return_range_pct is not None:
        low, high = preferences.aspirational_daily_return_range_pct
        if low == high:
            lines.append(f"- 희망 일 수익률(연구 목표): 약 {low:.0f}% (보장이 아닌 희망 조건)")
        else:
            lines.append(f"- 희망 일 수익률 범위(연구 목표): 약 {low:.0f}%~{high:.0f}% (보장이 아닌 희망 조건)")
    return lines


def reconcile_with_mission(mission, preferences: ResearchPreferences) -> str:
    """Combine ``preferences`` with an existing durable mission WITHOUT
    creating a new mission and WITHOUT claiming any persistence this module
    does not actually perform.

    ``mission`` is a ``gaon.knowledge.research_mission.ResearchMission`` or
    ``None`` - kept untyped here to avoid this module depending on the
    mission schema; callers pass whatever :meth:`LLMConversationBrain.
    _mission_for` returns. The mission's own scope (market / strategy
    family / universe) is always authoritative and is never overridden by a
    stated preference - a preference that does not conflict is folded in as
    a supplementary note only.
    """
    lines: list[str] = []
    if mission is None:
        lines.append(
            "영하님, 현재 진행 중인 연구 Mission이 없어 이 선호는 아직 어떤 Mission에도 반영되지 않았습니다."
        )
    else:
        lines.append(f"영하님, 기존 연구 Mission({mission.mission_id})의 범위는 그대로 유지합니다.")
        lines.append("새 Mission을 만들지 않고, 다음 선호를 참고 조건으로만 함께 반영합니다:")
    lines.append("")
    lines.extend(render_research_preferences_summary(preferences))
    lines.append("")
    lines.append(
        "승률과 일 수익률은 이번 연구가 지향하는 목표/희망 조건일 뿐이며, 실제 결과를 보장하거나 "
        "약속하는 수치가 아닙니다."
    )
    lines.append(
        "이 선호는 이번 대화 맥락에서만 참고되며, 별도의 데이터베이스에 저장되지는 않습니다."
    )
    return "\n".join(lines)
