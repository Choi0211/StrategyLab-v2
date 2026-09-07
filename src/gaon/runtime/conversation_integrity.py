"""General conversation-integrity layer (PR #213).

This module is the deterministic core of the three-stage conversation
contract the rest of the brain builds on:

1. INTERPRET  - is this turn a read-only conversational move (explain /
   translate / simplify / summarize / clarify / status / compare / why /
   opinion / recommendation / inspect / describe), or something else?
   ``read_only_intent`` / ``is_read_only_conversation``.

2. RESOLVE    - handled by the caller (``LLMConversationBrain``) using the
   persisted ``last_read_subject`` pointer plus durable ``ResearchMission``
   state; this module only classifies intent, it never touches storage.

3. AUTHORIZE  - does the turn EXPLICITLY request a state-changing research
   action?  ``authorizes_state_changing_research`` - a thin, single-source
   re-export of the existing deterministic
   ``has_explicit_research_execution_intent`` gate.  A conversational
   interpretation never grants execution permission by itself, and this
   stage stays purely deterministic and rule-gated.

CRITICAL RULE: when a turn is ambiguous, the caller prefers the read-only
interpretation.  ``is_read_only_conversation`` is intentionally inclusive
(a structural marker set, NOT a giant exact-phrase dictionary) precisely so
that "please explain" is never inferred as "please research again".
"""

from __future__ import annotations

import re

from gaon.knowledge.research_mission import (
    is_diversity_request,
    is_explicit_read_only_query,
    is_generic_continuation_request,
    is_stop_or_negation_request,
    requested_strategy_family,
)
from gaon.runtime.llm_tool_routing import has_explicit_research_execution_intent


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)


# Structural read-only-intent markers, grouped by the conceptual intent the
# task enumerates.  Each group is a small set of morphological markers
# (question endings, explanation verbs, reference pronouns), deliberately
# NOT whole canned phrases - broader natural phrasings resolve from these
# plus conversation context, and new phrasings do not need a new entry.
_READ_ONLY_MARKERS: dict[str, tuple[str, ...]] = {
    "translate": ("한글로", "한국어로", "번역", "영어로", "쉬운말로"),
    "simplify": ("쉽게", "쉽개", "간단히", "간단하게", "간략히", "초등학생", "쉬운말"),
    "summarize": ("요약", "정리해", "정리하면", "한줄로", "간단정리"),
    "clarify": (
        "무슨뜻", "뜻이야", "뜻이에요", "뜻인가", "무슨말", "뭔소리", "뭔말",
        "의미가", "무슨의미", "다시말해",
    ),
    "why": ("왜", "이유", "어째서", "왜냐", "때문", "무슨근거", "근거가뭐"),
    "explain": (
        "설명", "말해줘", "말해주세요", "말해봐", "알려줘", "알려주세요",
        "알려주실", "알아듣", "알아들", "풀어서", "풀어써", "이해가안",
        "이해안", "이해하게",
    ),
    "status": (
        "진행상황", "진행상태", "진척", "상황알려", "상태알려", "어떻게되",
        "어떻게돼", "어떻게된", "어디까지", "얼마나됐", "잘되", "잘돼",
        "잘진행", "진행되", "진행중", "막혀", "막혔", "멈춰", "멈췄",
        "아직도", "현재상태",
    ),
    "compare": (
        "제일좋", "가장좋", "제일나", "가장나", "더좋", "더나은", "비교",
        "차이가", "무슨차이", "우위", "낫나", "낫어", "낫습니",
    ),
    "opinion": ("어때", "어떤가", "괜찮", "어떻게생각", "생각해", "볼만"),
    "recommendation": (
        "추천", "뭐가좋", "뭘연구", "뭐연구", "다음엔", "다음에뭐", "다음에뭘",
        "다음연구", "뭘하는게", "뭘해야", "뭐해야", "어떤전략을연구",
    ),
    "inspect": (
        "자세히", "구체적", "더알려", "더설명", "상세히", "디테일", "详细",
        "좀더", "조금더",
    ),
    "describe": ("어떤전략", "무슨전략", "어떤후보", "무슨후보", "설명해주실"),
    "decision": (
        "결정해야", "정해야", "내가뭘", "내가뭐", "해야할게", "해야할것",
        "할게있", "결정할게", "결정할것", "승인해야",
    ),
    "reason_dropped": ("탈락", "떨어졌", "왜안", "왜못", "제외", "왜빠졌"),
}

# Bare backward-reference markers.  A short trailing-question turn that is
# nothing but a reference pronoun ("그건?", "바이낸스 쪽은?", "아까 그거?")
# is a read-only follow-up about the previous subject - it carries no
# content of its own and, crucially, no execution verb.
_REFERENCE_MARKERS: tuple[str, ...] = (
    "그건", "그거", "그게", "그것", "이건", "이거", "저건", "저거",
    "아까", "저번", "지난번", "그중", "그때", "거기", "그쪽", "쪽은",
    "그연구", "그전략", "그후보", "그결과", "그종목",
)


def read_only_intent(text: str) -> str | None:
    """The dominant read-only conversational intent for ``text`` - one of
    the keys of ``_READ_ONLY_MARKERS`` (``why`` / ``explain`` / ``translate``
    / ``simplify`` / ``summarize`` / ``clarify`` / ``status`` / ``compare``
    / ``opinion`` / ``recommendation`` / ``inspect`` / ``describe`` /
    ``decision`` / ``reason_dropped``) or ``"reference"`` for a bare
    backward-reference follow-up.  ``None`` when no read-only marker
    matches (the caller then keeps today's routing).

    This never inspects execution intent - see ``is_read_only_conversation``
    for the gated predicate callers should use to SUPPRESS mutation."""
    normalized = _norm(text)
    if not normalized:
        return None
    for kind, markers in _READ_ONLY_MARKERS.items():
        if any(marker in normalized for marker in markers):
            return kind
    stripped = text.strip()
    if len(stripped) <= 24 and (stripped.endswith("?") or len(normalized) <= 12):
        if any(marker in normalized for marker in _REFERENCE_MARKERS):
            return "reference"
    return None


def authorizes_state_changing_research(text: str) -> bool:
    """AUTHORIZE stage (deterministic, rule-gated): ``True`` only when the
    turn EXPLICITLY requests a state-changing research/validation action
    ("다시 연구해줘", "더 연구해줘", "새 후보를 만들어 검증해줘", "이 전략을
    재검증해줘").  A single source of truth - delegates to the existing
    ``has_explicit_research_execution_intent`` token gate.  Read-only
    phrasings ("왜?", "설명해줘", "한글로 말해줘", "상태 알려줘",
    "그건 어때?") never satisfy this."""
    return has_explicit_research_execution_intent(text)


def is_read_only_conversation(text: str) -> bool:
    """INTERPRET stage: ``True`` when this turn is a read-only conversational
    move that must NOT mutate operational state or launch research.

    Fail-closed to read-only: any recognised read-only marker (or a bare
    backward-reference follow-up) counts, UNLESS the same turn also carries
    an explicit state-changing research verb (``authorizes_state_changing_
    research``) - in which case it is a genuine research request and this
    returns ``False`` so the existing deterministic research/safety gates
    decide.  A STOP/negation request is handled by its own dedicated gate
    upstream and is not a read here."""
    if not text or not text.strip():
        return False
    if authorizes_state_changing_research(text):
        return False
    if is_stop_or_negation_request(text):
        return False
    if is_explicit_read_only_query(text):
        return True
    if read_only_intent(text) is not None:
        return True
    return False


def read_only_turn_may_not_mutate_mission(text: str) -> bool:
    """Convenience predicate for the mission read/continuation path: a turn
    that is read-only conversation AND is not an explicit continuation
    instruction must never reach ``extract_or_update_mission`` /
    ``_remember_mission`` / ``_try_mission_driven_research_cycle``.

    ``is_generic_continuation_request`` is excluded defensively even though
    ``is_read_only_conversation`` already rejects explicit execution verbs -
    "계속 연구해줘" style continuation has its own established routing and
    this predicate must not divert it.

    Two established directional-instruction shapes are also excluded so this
    change does not regress them: naming a specific strategy paradigm to run
    next ("평균회귀 전략은 어때?" - ``requested_strategy_family``, the A9
    feature) and asking for a different strategy family / rotation
    ("다른 방식도 찾아봐" - ``is_diversity_request``). Both name a concrete
    new research direction rather than asking to explain the previous
    answer, so they keep their existing mission-continuation routing."""
    if not is_read_only_conversation(text):
        return False
    if is_generic_continuation_request(text):
        return False
    if requested_strategy_family(text) is not None:
        return False
    if is_diversity_request(text):
        return False
    return True
