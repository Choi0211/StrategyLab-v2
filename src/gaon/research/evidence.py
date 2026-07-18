"""Evidence ranking and context building."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from gaon.research.search import SearchResult, canonical_url


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    title: str
    url: str
    content: str
    source_type: str
    retrieved_at: str
    content_hash: str
    relevance: float = 0.0
    freshness: float = 0.0
    source_quality: float = 0.0
    corroborated: bool = False
    contradiction: bool = False


@dataclass(frozen=True)
class Citation:
    citation_id: str
    evidence_id: str
    url: str
    title: str


@dataclass(frozen=True)
class EvidenceBundle:
    items: tuple[EvidenceItem, ...]
    citations: tuple[Citation, ...]
    context: str
    truncated: bool
    diagnostics: tuple[str, ...]


def evidence_from_search(result: SearchResult, *, query: str, source_quality_rules: dict[str, float] | None = None) -> EvidenceItem:
    url = canonical_url(result.url)
    content_hash = stable_content_hash(result.content)
    domain = result.source.domain
    quality = (source_quality_rules or {}).get(domain, 0.5)
    relevance = _token_score(query, f"{result.title} {result.content}")
    freshness = 1.0 if result.source.retrieved_at else 0.0
    evidence_id = f"ev:{hashlib.sha256((url + content_hash).encode('utf-8')).hexdigest()[:16]}"
    return EvidenceItem(evidence_id, result.title, url, result.content, result.source.provider, result.source.retrieved_at, content_hash, relevance, freshness, quality)


def build_evidence_bundle(
    external: tuple[EvidenceItem, ...],
    memory: tuple[EvidenceItem, ...] = (),
    *,
    context_budget_chars: int = 4000,
) -> EvidenceBundle:
    deduped, duplicate_count = remove_duplicates((*external, *memory))
    corroborated = _mark_corroboration(deduped)
    ranked = tuple(sorted(corroborated, key=lambda item: (-_score(item), item.url, item.evidence_id)))
    citations = tuple(Citation(f"C{i + 1}", item.evidence_id, item.url, item.title) for i, item in enumerate(ranked))
    lines: list[str] = []
    used = 0
    truncated = False
    for citation, item in zip(citations, ranked):
        line = f"[{citation.citation_id}] {item.title}: {item.content}"
        if used + len(line) + 1 > context_budget_chars:
            truncated = True
            break
        lines.append(line)
        used += len(line) + 1
    diagnostics: list[str] = []
    if duplicate_count:
        diagnostics.append(f"deduplicated={duplicate_count}")
    if truncated:
        diagnostics.append("context_truncated")
    if any(item.contradiction for item in ranked):
        diagnostics.append("contradictions_preserved")
    return EvidenceBundle(ranked, citations, "\n".join(lines), truncated, tuple(diagnostics))


def remove_duplicates(items: tuple[EvidenceItem, ...]) -> tuple[tuple[EvidenceItem, ...], int]:
    seen_hashes: set[str] = set()
    seen_near: set[str] = set()
    kept: list[EvidenceItem] = []
    dropped = 0
    for item in items:
        near = _near_key(item.content)
        if item.content_hash in seen_hashes or near in seen_near:
            dropped += 1
            continue
        seen_hashes.add(item.content_hash)
        seen_near.add(near)
        kept.append(item)
    return tuple(kept), dropped


def stable_content_hash(content: str) -> str:
    return hashlib.sha256(" ".join(content.split()).casefold().encode("utf-8")).hexdigest()


def _score(item: EvidenceItem) -> float:
    return item.relevance * 0.5 + item.freshness * 0.2 + item.source_quality * 0.2 + (0.1 if item.corroborated else 0.0)


def _token_score(query: str, content: str) -> float:
    query_tokens = set(query.casefold().split())
    content_tokens = set(content.casefold().split())
    if not query_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)


def _near_key(content: str) -> str:
    words = " ".join(content.casefold().split()).split()
    return " ".join(words[:24])


def _mark_corroboration(items: tuple[EvidenceItem, ...]) -> tuple[EvidenceItem, ...]:
    title_counts: dict[str, int] = {}
    for item in items:
        key = item.title.casefold()
        title_counts[key] = title_counts.get(key, 0) + 1
    return tuple(
        EvidenceItem(**{**item.__dict__, "corroborated": title_counts[item.title.casefold()] > 1})
        for item in items
    )
