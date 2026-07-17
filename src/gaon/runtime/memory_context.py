"""Read-only Learning Memory and Research Brain context builder."""

from __future__ import annotations

from typing import Protocol

from gaon.learning.repository import LearningRepository
from gaon.learning.retrieval import RelatedMemoryMode, RelatedMemoryQuery
from gaon.runtime.context import ContextBuildResult, ContextReference, ConversationContext, ResearchContext, RetrievedMemory
from gaon.runtime.intents import Intent

CONTEXT_INTENTS = {
    Intent.RECENT_RESEARCH,
    Intent.SEARCH_MEMORY,
    Intent.TODAY_PLAN,
    Intent.RESEARCH_STATUS,
    Intent.REVALIDATION_DUE,
    Intent.CONFLICTS,
    Intent.DUPLICATES,
}


class ResearchContextReader(Protocol):
    def summarize(self, *, query: str, intent: Intent) -> ResearchContext: ...


class EmptyResearchContextReader:
    def summarize(self, *, query: str, intent: Intent) -> ResearchContext:
        return ResearchContext(
            sessions_summary="연결된 Research Brain 기록이 부족합니다.",
            outcomes_summary="연결된 ResearchOutcome 기록이 부족합니다.",
            warnings=("research context unavailable",),
        )


class MemoryContextBuilder:
    """Build deterministic read-only conversation context."""

    def __init__(
        self,
        repository: LearningRepository,
        research_reader: ResearchContextReader | None = None,
        *,
        scope: str = "strategy-research",
        project: str = "StrategyLab",
        strategy: str = "ORB",
        market: str = "KRX",
        limit: int = 3,
    ) -> None:
        self._repository = repository
        self._research_reader = research_reader or EmptyResearchContextReader()
        self._scope = scope
        self._project = project
        self._strategy = strategy
        self._market = market
        self._limit = limit

    def should_build(self, intent: Intent) -> bool:
        return intent in CONTEXT_INTENTS

    def build(self, message, intent: Intent) -> ContextBuildResult:
        query = message.text.strip()
        records, retrieval_warnings = self._retrieve_with_fallback(query, message.received_at)
        claims = tuple(claim.statement for claim in self._repository.list_claims()[: self._limit])
        research = self._research_reader.summarize(query=query, intent=intent)
        references = tuple(reference for record in records for reference in record.references) + research.references
        warnings = (*retrieval_warnings, *tuple(warning for record in records for warning in record.warnings), *research.warnings)
        if not records:
            warnings = (*warnings, "related memory unavailable")
        return ContextBuildResult(
            ConversationContext(
                conversation_id=message.conversation_id,
                user_id=message.user_id,
                query=query,
                intent=intent,
                project=self._project,
                strategy=self._strategy,
                market=self._market,
                retrieved_records=records,
                claims=claims,
                research=research,
                warnings=_dedupe(warnings),
                references=_dedupe_refs(references),
                generated_at=message.received_at,
            )
        )

    def _retrieve_with_fallback(self, query: str, reference_time: str) -> tuple[tuple[RetrievedMemory, ...], tuple[str, ...]]:
        warnings: list[str] = []
        for mode in (RelatedMemoryMode.STRICT, RelatedMemoryMode.BROAD, RelatedMemoryMode.GLOBAL):
            results = self._repository.retrieve_related(
                RelatedMemoryQuery(
                    scope=self._scope,
                    project=self._project,
                    strategy=self._strategy,
                    market=self._market,
                    query=query,
                    limit=self._limit,
                    reference_time=reference_time,
                    mode=mode,
                )
            )
            if results:
                if mode is not RelatedMemoryMode.STRICT:
                    warnings.append(f"{mode.value} fallback used")
                return _dedupe_records(tuple(_to_memory(result) for result in results)), tuple(warnings)
        return (), ("no related memory found",)


def summarize_context(context: ConversationContext) -> str:
    if not context.retrieved_records:
        return "영하님, 관련 Learning Memory 기록을 찾지 못했습니다. 연결된 기록이 부족하므로 확정 사실로 표현하지 않겠습니다."
    lines = [f"영하님, 관련 기록 {len(context.retrieved_records)}건을 찾았습니다."]
    need_validation = sum(1 for record in context.retrieved_records if record.validation_state == "need_validation")
    if need_validation:
        lines.append(f"이 중 {need_validation}건은 아직 검증이 필요합니다.")
    if any(record.conflict_state != "clear" for record in context.retrieved_records):
        lines.append("충돌 후보가 있어 확정 사실로 표현하지 않겠습니다.")
    if any(record.revalidation_state in {"overdue", "due"} for record in context.retrieved_records):
        lines.append("재검증이 필요한 기록이 포함되어 있습니다.")
    lines.append("Confidence는 정렬 보조 신호일 뿐 승인 권한이 아닙니다.")
    for record in context.retrieved_records:
        lines.append(f"- {record.record_id}: {record.content}")
    return "\n".join(lines)


def _to_memory(result) -> RetrievedMemory:
    record = result.record
    references = tuple(
        ContextReference(evidence.evidence_id, evidence.reference, evidence.summary)
        for evidence in record.evidence
    )
    return RetrievedMemory(
        record_id=record.record_id,
        content=record.content,
        record_type=record.record_type.value,
        validation_state=record.confidence.validation_state,
        confidence=record.confidence.value,
        conflict_state=result.conflict_state,
        revalidation_state=result.revalidation_state,
        warnings=result.warnings,
        references=references,
    )


def _dedupe_records(records: tuple[RetrievedMemory, ...]) -> tuple[RetrievedMemory, ...]:
    seen: set[str] = set()
    deduped: list[RetrievedMemory] = []
    for record in records:
        if record.record_id in seen:
            continue
        seen.add(record.record_id)
        deduped.append(record)
    return tuple(deduped)


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _dedupe_refs(values: tuple[ContextReference, ...]) -> tuple[ContextReference, ...]:
    seen: set[str] = set()
    refs: list[ContextReference] = []
    for value in values:
        if value.reference_id in seen:
            continue
        seen.add(value.reference_id)
        refs.append(value)
    return tuple(refs)
