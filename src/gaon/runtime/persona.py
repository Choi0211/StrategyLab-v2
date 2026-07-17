"""Deterministic Korean persona responses for Gaon."""

from __future__ import annotations

from gaon.runtime.intents import Intent

RULE_BASED_ROUTE = "rule_based"


def persona_text(intent: Intent) -> str:
    mapping = {
        Intent.GREETING: "안녕하세요, 영하님. 가온입니다. 무엇을 함께 살펴볼까요?",
        Intent.CALL_GAON: "네, 영하님. 무엇을 도와드릴까요?",
        Intent.HELP: (
            "영하님, 현재 저는 연구 대화, 상태 확인, 오늘 계획 안내, 최근 연구/기억 조회 요청 이해, "
            "Telegram smoke 연결 확인을 도와드릴 수 있습니다. 시장 데이터, 일정, 종목 분석, 백테스트 실행은 "
            "아직 별도 실행기와 연결되지 않았습니다. 사용 가능한 slash 명령은 /help /status /today /research "
            "/memory <query> /conflicts /duplicates /revalidate /daily /weekly /notion-sync /approvals 입니다."
        ),
        Intent.STATUS: "영하님, Gaon Runtime은 응답 가능한 상태입니다. 현재 대화는 deterministic rule-based 경로로 처리되며 dry-run 안전 경계를 유지합니다.",
        Intent.TODAY_PLAN: (
            "영하님, 오늘은 먼저 진행 중인 Sprint와 테스트 상태를 확인하고, 그 다음 연구 요청을 작은 단위로 정리하는 것이 좋겠습니다. "
            "실제 일정 시스템은 아직 연결되지 않았습니다."
        ),
        Intent.MARKET_STATUS: (
            "영하님, 시장 상태를 확인하려는 요청으로 이해했습니다. 다만 현재 공개 StrategyLab-v2에는 아직 실시간 시장 데이터 연결이 없어서 "
            "시장 상황을 조회하거나 판단하지 않았습니다. 다음 단계는 안전한 market data adapter를 별도 계약으로 연결하는 것입니다."
        ),
        Intent.STOCK_ANALYSIS: (
            "영하님, 종목 분석 요청으로 이해했습니다. 현재는 아직 실제 시세, 재무 데이터, 뉴스, 백테스트 실행기가 연결되어 있지 않아 "
            "분석 결과를 만든 것처럼 답하지 않겠습니다. 다음 단계는 데이터 출처와 분석 계약을 먼저 정의하는 것입니다."
        ),
        Intent.SCHEDULE: (
            "영하님, 일정 확인 요청으로 이해했습니다. 아직 캘린더나 작업 스케줄 저장소가 연결되어 있지 않아 실제 일정을 조회하지 않았습니다. "
            "다음 단계는 일정 provider 계약과 읽기 전용 조회 범위를 설계하는 것입니다."
        ),
        Intent.BACKTEST: (
            "영하님, 백테스트 실행 요청으로 이해했습니다. 현재 Telegram 대화에는 아직 백테스트 실행기가 연결되어 있지 않아 실행하지 않습니다. "
            "다음 단계는 승인된 Research Plan과 안전한 backtest port를 연결하는 것입니다."
        ),
        Intent.RECENT_RESEARCH: (
            "영하님, 지난 연구 조회 요청으로 이해했습니다. 현재 대화 런타임은 실제 Learning Memory 조회 결과를 붙이지 않았습니다. "
            "다음 단계는 읽기 전용 memory retrieval을 대화 응답에 연결하는 것입니다."
        ),
        Intent.SEARCH_MEMORY: (
            "영하님, 기억 검색 요청으로 이해했습니다. 아직 이 대화 경로에는 실제 Learning Memory 검색기가 연결되지 않았습니다. "
            "검색 요청 자체만 안전하게 분류했습니다."
        ),
        Intent.RESEARCH_STATUS: "영하님, 연구 상태 조회 요청을 확인했습니다. 현재는 저장된 연구 실행 상태를 직접 조회하지 않는 안전 응답입니다.",
        Intent.CONFLICTS: "영하님, 충돌 후보 조회 요청을 확인했습니다. 자동 해결이나 자동 승인은 수행하지 않습니다.",
        Intent.DUPLICATES: "영하님, 중복 후보 조회 요청을 확인했습니다. 자동 병합은 수행하지 않습니다.",
        Intent.REVALIDATION_DUE: "영하님, 재검증 대상 조회 요청을 확인했습니다. 자동 검증 전환은 수행하지 않습니다.",
        Intent.DAILY_REPORT: "영하님, 일일 리포트 요청을 확인했습니다. 현재 대화에서는 dry-run 리포트 경계만 제공합니다.",
        Intent.WEEKLY_REVIEW: "영하님, 주간 리뷰 요청을 확인했습니다. 현재 대화에서는 dry-run 리뷰 경계만 제공합니다.",
        Intent.SYNC_NOTION: "영하님, Notion 동기화 요청을 확인했습니다. 현재는 실제 Notion 네트워크 연결을 실행하지 않습니다.",
        Intent.APPROVAL_STATUS: "영하님, 승인 상태 조회만 지원합니다. 이 런타임은 투자 승인이나 정책 승인을 자동 수행하지 않습니다.",
        Intent.UNKNOWN: "죄송하지만 요청을 정확히 이해하지 못했습니다, 영하님. ‘도움말’이라고 말씀해 주시면 현재 가능한 기능을 안내해 드리겠습니다.",
    }
    return mapping[intent]


def safety_warning(text: str) -> str | None:
    normalized = text.casefold()
    unsafe_tokens = ("매수", "매도", "주문", "실거래", "자동 승인", "approve", "buy", "sell", "order")
    if any(token in normalized for token in unsafe_tokens):
        return "투자 주문, 실거래, 자동 승인은 이 런타임에서 수행하지 않습니다."
    return None
