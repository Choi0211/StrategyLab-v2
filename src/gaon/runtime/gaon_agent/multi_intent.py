"""Multi-intent foundation: split a message that asks several *separate*
things, so no question is silently dropped.

Deliberately conservative - a wrong split is worse than a missed one,
because each segment is then routed independently. It splits ONLY on
unambiguous authoring boundaries:

* a blank line between blocks ("question one" \\n\\n "question two"), or
* an explicit enumerated list (``1.`` / ``2)`` / ``- `` markers, 2+).

It never splits on a single line break or on ordinary sentence
punctuation, so a normal multi-sentence request ("...전략을 연구해주세요.
실제 데이터로 백테스트해줘") stays one segment. Each resulting segment
must also independently read like a request (>= :data:`_MIN_SEGMENT_CHARS`
characters, with a question / request ending or an interrogative word),
otherwise the whole message is kept intact. Bounded to :data:`MAX_SEGMENTS`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_SEGMENTS = 3
_MIN_SEGMENT_CHARS = 6
# A genuine "two quick questions" turn is short. A long structured request
# (a multi-paragraph research brief) is one intent even with blank lines.
_MAX_TOTAL_CHARS = 300
_MAX_SEGMENT_CHARS = 160

# An interrogative / request shape - used to confirm a candidate segment is
# actually its own ask before we agree to split.
_REQUESTY_RE = re.compile(
    r"(?:\?|？|까요|나요|가요|까\b|어\?|해줘|해 줘|해주세요|알려|말해|설명|뭐|무엇|뭔|왜|어떻게|어때|누구|언제|어디|필요)"
)


@dataclass(frozen=True)
class TurnSegment:
    index: int
    text: str


_ENUMERATION_RE = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•]|[가-힣][.)])\s+")


def _looks_meaningful(chunk: str) -> bool:
    stripped = chunk.strip()
    if len(stripped) < _MIN_SEGMENT_CHARS:
        return False
    if not re.search(r"[가-힣A-Za-z0-9]", stripped):
        return False
    return bool(_REQUESTY_RE.search(stripped))


def _raw_chunks(text: str) -> list[str]:
    # 1) blank-line separated blocks
    blocks = [block for block in re.split(r"\n\s*\n", text) if block.strip()]
    if len(blocks) > 1:
        return blocks
    # 2) explicit enumeration markers (need at least two)
    if len(_ENUMERATION_RE.findall(text)) > 1:
        parts = _ENUMERATION_RE.split(text)
        return [part for part in parts if part.strip()]
    return [text]


def segment_turn(text: str) -> tuple[TurnSegment, ...]:
    """Split ``text`` into ordered :class:`TurnSegment` items.

    Returns a single segment (the whole message) when there is no strong
    multi-intent boundary - callers treat a one-tuple result as "not
    multi-intent" and route normally.
    """
    if not text or not text.strip():
        return (TurnSegment(0, text),)
    if len(text.strip()) > _MAX_TOTAL_CHARS:
        return (TurnSegment(0, text.strip()),)
    chunks = [chunk.strip() for chunk in _raw_chunks(text)]
    meaningful = [chunk for chunk in chunks if _looks_meaningful(chunk)]
    # Every non-trivial chunk must be an independent short ask. If a chunk is
    # long, or a chunk carries content but is not itself request-shaped, the
    # message is one intent (fail safe: do not split).
    if len(meaningful) != len([c for c in chunks if len(c) >= _MIN_SEGMENT_CHARS]):
        return (TurnSegment(0, text.strip()),)
    if not (2 <= len(meaningful) <= MAX_SEGMENTS):
        return (TurnSegment(0, text.strip()),)
    if any(len(chunk) > _MAX_SEGMENT_CHARS for chunk in meaningful):
        return (TurnSegment(0, text.strip()),)
    return tuple(TurnSegment(index, chunk) for index, chunk in enumerate(meaningful))


def recompose_answers(answers: tuple[str, ...]) -> str:
    """Join per-segment answers into one reply, dropping empties and exact
    duplicates while preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for answer in answers:
        cleaned = (answer or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return "\n\n".join(ordered)
