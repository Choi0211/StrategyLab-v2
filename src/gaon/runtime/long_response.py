"""Long response composition helpers for bounded provider continuation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContinuationResult:
    text: str
    continuation_count: int
    truncated: bool
    warnings: tuple[str, ...]


def merge_response_parts(parts: tuple[str, ...]) -> str:
    merged = ""
    for part in parts:
        clean = part.strip()
        if not clean:
            continue
        if not merged:
            merged = clean
            continue
        overlap = _overlap_suffix_prefix(merged, clean)
        separator = "" if overlap else "\n\n"
        merged = f"{merged}{separator}{clean[overlap:]}"
    return merged


def continuation_prompt(original_text: str, partial_text: str) -> str:
    tail = partial_text[-1200:]
    return (
        "아래 답변은 길이 제한 때문에 중간에서 끊겼습니다.\n"
        "이미 작성한 내용을 반복하지 말고, 이어지는 다음 부분만 한국어 존댓말로 작성해 주세요.\n"
        "숨겨진 reasoning, chain-of-thought, API 키, 토큰, secret은 노출하지 마세요.\n\n"
        f"[원래 사용자 요청]\n{original_text[:2000]}\n\n"
        f"[이미 전달된 답변의 마지막 부분]\n{tail}"
    )


def _overlap_suffix_prefix(left: str, right: str, max_size: int = 300) -> int:
    limit = min(len(left), len(right), max_size)
    for size in range(limit, 0, -1):
        if left[-size:] == right[:size]:
            return size
    return 0
