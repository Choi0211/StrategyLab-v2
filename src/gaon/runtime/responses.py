"""Conversation response helpers."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.runtime.intents import Intent


@dataclass(frozen=True)
class ResponseAction:
    action_type: str
    dry_run: bool = True


def fallback_text() -> str:
    return "요청을 확실히 이해하지 못했습니다. /help 로 가능한 명령을 확인할 수 있습니다."


def help_text() -> str:
    return "지원 명령: /help /status /today /research /memory <query> /conflicts /duplicates /revalidate /daily /weekly /notion-sync /approvals"


def intent_text(intent: Intent) -> str:
    mapping = {
        Intent.STATUS: "Gaon runtime is available in dry-run mode.",
        Intent.TODAY_PLAN: "오늘 계획은 명시적으로 저장된 연구/재검증 항목 기준으로만 생성됩니다.",
        Intent.RESEARCH_STATUS: "연구 상태 조회 요청을 확인했습니다.",
        Intent.SEARCH_MEMORY: "관련 기억 검색 요청을 확인했습니다.",
        Intent.CONFLICTS: "충돌 후보 조회 요청을 확인했습니다.",
        Intent.DUPLICATES: "중복 후보 조회 요청을 확인했습니다.",
        Intent.REVALIDATION_DUE: "재검증 필요 항목 조회 요청을 확인했습니다.",
        Intent.DAILY_REPORT: "Daily Report 생성 요청을 dry-run으로 준비했습니다.",
        Intent.WEEKLY_REVIEW: "Weekly Review 생성 요청을 dry-run으로 준비했습니다.",
        Intent.SYNC_NOTION: "Notion 동기화 요청을 dry-run payload로 준비했습니다.",
        Intent.APPROVAL_STATUS: "승인 대기 상태 조회만 지원합니다. 이 Runtime은 승인을 자동 생성하지 않습니다.",
    }
    return mapping.get(intent, fallback_text())
