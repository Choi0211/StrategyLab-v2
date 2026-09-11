"""Thin conversational routing seam (PR #214).

``GaonTurnRouter`` sits in ``LLMConversationBrain._generate`` right after the
deterministic approval gate. It owns only the lanes the current pipeline
mis-serves:

* **MULTI_INTENT** - a message asking several things; each part is routed
  and the answers recomposed.
* **URL_LIMITATION / CURRENT_INFO_LIMITATION / MULTIMODAL_LIMITATION** -
  the user wants Gaon to read a link / look up live info / inspect media
  it cannot access yet; answer honestly from the capability registry
  instead of fabricating or dumping a generic complaint template.

Everything else returns ``PASS_THROUGH`` and the existing routing (general
conversation -> LLM, mission reads, research execution, safety gate) runs
unchanged. The router never grants a capability and never touches state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from gaon.runtime.gaon_agent.capabilities import (
    CapabilityRegistry,
    IMAGE_VISION,
    MARKET_DATA_READ,
    URL_FETCH,
    WEB_SEARCH,
)
from gaon.runtime.gaon_agent.multi_intent import TurnSegment, segment_turn
from gaon.runtime.gaon_agent.multimodal import Modality, describe_multimodal_request


class TurnLane(str, Enum):
    PASS_THROUGH = "pass_through"
    MULTI_INTENT = "multi_intent"
    URL_LIMITATION = "url_limitation"
    CURRENT_INFO_LIMITATION = "current_info_limitation"
    MULTIMODAL_LIMITATION = "multimodal_limitation"


@dataclass(frozen=True)
class RoutedTurn:
    lane: TurnLane
    text: str = ""
    route_name: str = ""
    warnings: tuple[str, ...] = ()
    segments: tuple[TurnSegment, ...] = ()
    modality: Modality | None = None


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_BARE_SOCIAL_RE = re.compile(
    r"\b(?:www\.)?(?:instagram\.com|instagr\.am|youtu\.be|youtube\.com|twitter\.com|x\.com|"
    r"tiktok\.com|facebook\.com|fb\.watch|threads\.net|blog\.naver\.com|cafe\.naver\.com|"
    r"m\.blog\.naver\.com|brunch\.co\.kr)/\S+",
    re.IGNORECASE,
)

_RESEARCH_GUARD_TOKENS = ("전략", "연구", "백테스트", "backtest", "후보", "candidate", "미션", "mission")

_CURRENT_INFO_WEATHER = ("날씨", "기온", "미세먼지", "비 와", "비가 와", "비 올", "우산", "폭염", "한파")
_CURRENT_INFO_MARKET = (
    "비트코인", "비트 코인", "btc", "이더리움", "eth", "환율", "달러 값", "원달러", "코스피 지수",
    "코스닥 지수", "나스닥", "s&p", "금값", "금 시세", "유가", "주가", "시세", "가격",
)
_CURRENT_INFO_NEWS = ("오늘 뉴스", "최신 뉴스", "방금 뉴스", "속보", "지금 뉴스", "요즘 뉴스")
_NOW_MARKERS = ("지금", "현재", "오늘", "실시간", "얼마", "몇 도", "며칠", "요즘")


def contains_external_url(text: str) -> bool:
    return bool(_URL_RE.search(text) or _BARE_SOCIAL_RE.search(text))


def is_current_info_question(text: str) -> bool:
    normalized = text.casefold()
    if any(token in normalized for token in _RESEARCH_GUARD_TOKENS):
        return False
    if any(token in normalized for token in _CURRENT_INFO_NEWS):
        return True
    if any(token in normalized for token in _CURRENT_INFO_WEATHER):
        return True
    if any(token in normalized for token in _CURRENT_INFO_MARKET) and any(
        token in normalized for token in _NOW_MARKERS
    ):
        return True
    return False


class GaonTurnRouter:
    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._registry = capability_registry

    # -- classification ---------------------------------------------------
    def classify(self, text: str, *, defer: bool = False, allow_multi: bool = True) -> RoutedTurn:
        """Classify a turn into a lane.

        ``defer`` - the caller has already decided the mission / research
        pipeline owns this turn; only a genuine multi-question split may
        still override it. ``allow_multi`` - set ``False`` for an explicit
        research-execution turn so a structured multi-paragraph brief is
        never sliced into fragments.
        """
        if not text or not text.strip():
            return RoutedTurn(TurnLane.PASS_THROUGH)

        if allow_multi:
            segments = segment_turn(text)
            if len(segments) > 1:
                return RoutedTurn(
                    TurnLane.MULTI_INTENT, route_name="conversation_multi_intent", segments=segments
                )

        # Capability-limitation lanes are checked BEFORE ``defer`` on purpose:
        # "이 스크린샷 분석해줘" / "이 링크 봐줘" superficially look like a
        # research verb, but Gaon cannot access the media/link at all - the
        # honest limitation reply is always the right answer, and it never
        # touches state. These predicates are narrow (a real URL, a media
        # inspect request, a live-info question with a "now" marker) and
        # already exclude research-topic phrasing.
        media = describe_multimodal_request(text)
        if media is not None and not self._registry.is_available(media.capability_id):
            return RoutedTurn(
                TurnLane.MULTIMODAL_LIMITATION,
                text=render_multimodal_limitation(media.modality, self._registry),
                route_name="conversation_capability_limited_multimodal",
                warnings=(f"{media.capability_id} unavailable; no fabricated media analysis",),
                modality=media.modality,
            )

        if contains_external_url(text) and not self._registry.is_available(URL_FETCH):
            return RoutedTurn(
                TurnLane.URL_LIMITATION,
                text=render_url_limitation(self._registry),
                route_name="conversation_capability_limited_url",
                warnings=(f"{URL_FETCH} unavailable; link not fetched, no content claimed",),
            )

        if is_current_info_question(text) and not self._has_live_info_capability():
            return RoutedTurn(
                TurnLane.CURRENT_INFO_LIMITATION,
                text=render_current_info_limitation(),
                route_name="conversation_capability_limited_current_info",
                warnings=("no live-info provider; current value not fabricated",),
            )

        # ``defer`` and the default both mean "let the existing pipeline
        # handle it" - kept explicit so the contract stays legible.
        if defer:
            return RoutedTurn(TurnLane.PASS_THROUGH)
        return RoutedTurn(TurnLane.PASS_THROUGH)

    def _has_live_info_capability(self) -> bool:
        # MARKET_DATA_READ is a historical / research pipeline, not a live
        # ticker; WEB_SEARCH is a fixture. Neither answers "right now".
        return self._registry.is_available(WEB_SEARCH)


# -- renderers ----------------------------------------------------------------
_EXTERNAL_RESEARCH_TOKENS: tuple[str, ...] = ("인터넷에서", "웹에서", "온라인에서", "인터넷 검색", "웹 검색", "웹검색")
_EXTERNAL_RESEARCH_VERBS: tuple[str, ...] = ("찾아", "검색해")


def wants_external_web_research(text: str) -> bool:
    """``True`` when the turn explicitly asks Gaon to go find material on
    the internet/web itself (roadmap #217 follow-up: multi-intent partial
    fulfilment - "부족한 자료도 인터넷에서 찾아서 계속 연구해줘"). Requires
    both a place-token ("인터넷에서" / "웹에서" / ...) and a fetch verb
    ("찾아" / "검색해") so an unrelated sentence never misfires this."""
    normalized = text.casefold()
    return any(token in normalized for token in _EXTERNAL_RESEARCH_TOKENS) and any(
        verb in normalized for verb in _EXTERNAL_RESEARCH_VERBS
    )


def render_external_research_limitation() -> str:
    return (
        "참고로 지금은 인터넷에서 직접 자료를 찾아오는 기능이 아직 연결되어 있지 않아, "
        "그 부분만은 자동으로 수행하지 못했습니다. 필요한 자료를 텍스트로 붙여 주시면 "
        "그 내용을 반영해 연구를 이어가겠습니다."
    )


def render_url_limitation(registry: CapabilityRegistry) -> str:
    base = (
        "영하님, 저는 아직 링크를 직접 열어 내용을 가져올 수 없습니다. "
        "게시물이나 페이지의 내용을 텍스트로 붙여 주시면 그 내용을 바탕으로 분석해 드리겠습니다."
    )
    if registry.is_available(IMAGE_VISION):
        base += " 화면 스크린샷을 보내 주셔도 됩니다."
    return base


def render_current_info_limitation() -> str:
    return (
        "영하님, 지금은 실시간 정보(날씨·시세·환율·뉴스 등)를 조회할 수 있는 도구가 연결되어 있지 않아 "
        "최신 값을 정확히 확인해 드릴 수 없습니다. 값을 알려 주시면 그 값을 근거로 설명해 드리겠습니다."
    )


def render_multimodal_limitation(modality: Modality, registry: CapabilityRegistry) -> str:
    if modality is Modality.IMAGE:
        return (
            "영하님, 지금은 이미지나 스크린샷을 직접 볼 수 있는 기능이 연결되어 있지 않습니다. "
            "화면의 핵심 내용을 글로 적어 주시면 분석해 드리겠습니다."
        )
    if modality is Modality.VIDEO:
        return (
            "영하님, 지금은 영상이나 자막을 직접 가져와 분석할 수 있는 기능이 없습니다. "
            "영상에서 이야기하는 핵심 주장이나 자막 텍스트를 붙여 주시면 검토해 드리겠습니다."
        )
    return (
        "영하님, 지금은 PDF나 문서 파일을 직접 읽을 수 있는 기능이 연결되어 있지 않습니다. "
        "핵심 부분을 텍스트로 보내 주시면 분석해 드리겠습니다."
    )
