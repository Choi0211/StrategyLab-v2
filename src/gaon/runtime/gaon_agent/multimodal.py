"""Multimodal capability abstraction (providers land in PR #217).

PR #214 only needs to *recognise* when a user is asking Gaon to look at
something it cannot look at yet - an image, a screenshot, a video, a PDF -
so the conversational layer can say so honestly instead of pretending.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from gaon.runtime.gaon_agent.capabilities import (
    DOCUMENT_READ,
    IMAGE_VISION,
    VIDEO_TRANSCRIPT,
)


class Modality(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"


# Capability id that must be AVAILABLE for Gaon to actually handle each modality.
MODALITY_CAPABILITY: dict[Modality, str] = {
    Modality.IMAGE: IMAGE_VISION,
    Modality.VIDEO: VIDEO_TRANSCRIPT,
    Modality.DOCUMENT: DOCUMENT_READ,
}

_IMAGE_MARKERS = (
    "사진", "스크린샷", "스크린 샷", "캡처", "캡쳐", "이미지", "그림", "차트 이미지",
    "화면 캡", "screenshot", "이 짤",
)
_VIDEO_MARKERS = (
    "영상", "동영상", "비디오", "유튜브", "youtube", "쇼츠", "shorts", "릴스", "reels",
    "이 클립", "영상 좀", "영상 한번",
)
_DOCUMENT_MARKERS = (
    "pdf", "피디에프", "문서 파일", "이 문서", "첨부한 파일", "보낸 파일", "리포트 파일",
    "논문", "보고서 파일", "엑셀 파일", "한글 파일", "docx",
)
# "look at this" style verbs that turn a bare noun into a request to inspect it.
_INSPECT_MARKERS = (
    "봐", "보고", "봐줘", "봐봐", "확인해", "분석해", "읽어", "읽고", "해석해", "어때", "어떤가",
    "정리해", "설명해",
)


@dataclass(frozen=True)
class MultimodalReference:
    modality: Modality
    capability_id: str
    marker: str


def describe_multimodal_request(text: str) -> MultimodalReference | None:
    """Return the dominant multimodal reference in ``text`` (image > video >
    document by specificity), or ``None`` when the message is not asking Gaon
    to look at attached media.

    A bare mention is not enough - the message must also carry an inspect
    verb, so "영상 편집 알려줘" (a how-to question) does not trigger a
    limitation reply while "이 영상 좀 봐줘" does.
    """
    normalized = text.casefold()
    if not any(marker in normalized for marker in _INSPECT_MARKERS):
        # ...unless the media noun is itself glued to an inspect intent that
        # our short marker list missed - keep this conservative.
        if not re.search(r"(사진|스크린샷|영상|유튜브|pdf|문서).{0,6}(줘|주세요|해줘|해주세요)", normalized):
            return None
    for modality, markers in (
        (Modality.IMAGE, _IMAGE_MARKERS),
        (Modality.VIDEO, _VIDEO_MARKERS),
        (Modality.DOCUMENT, _DOCUMENT_MARKERS),
    ):
        for marker in markers:
            if marker in normalized:
                return MultimodalReference(modality, MODALITY_CAPABILITY[modality], marker)
    return None
