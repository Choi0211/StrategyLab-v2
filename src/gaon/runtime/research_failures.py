"""Structured failure classification for Telegram-facing research paths."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.runtime.assistant_provider import ProviderTimeoutError


@dataclass(frozen=True)
class ResearchFailure:
    stage: str
    error_type: str
    retryable: bool
    user_message: str


def classify_tool_failure(error_type: str, message: str = "") -> ResearchFailure:
    normalized = f"{error_type} {message}".casefold()
    if "realmarketdataunavailable" in normalized or "real_data_unavailable" in normalized:
        if "blocking_quality" in normalized or "quality" in normalized or "invalid_ohlc" in normalized or "duplicate" in normalized:
            return ResearchFailure("quality", error_type, False, "영하님, 시장 데이터 품질 문제로 백테스트를 중단했습니다. 결과를 임의로 만들지 않겠습니다.")
        return ResearchFailure("market_data", error_type, True, "영하님, 실제 시장 데이터를 가져오지 못해 연구를 수행하지 못했습니다. 결과를 임의로 만들지 않겠습니다.")
    if "dataquality" in normalized or "blocking_quality" in normalized or "invalid_ohlc" in normalized or "duplicate" in normalized:
        return ResearchFailure("quality", error_type, False, "영하님, 시장 데이터 품질 문제로 백테스트를 중단했습니다. 결과를 임의로 만들지 않겠습니다.")
    # fix/rule-based-engine-fail-closed: an UnsupportedStrategySpecError /
    # UnsupportedStrategyRuleError from RuleBasedBacktestEngine means the
    # strategy carries a rule the backtest engine does not implement - not
    # retryable, and NOT a generic tool glitch. Surfaced as its own
    # "engine_capability" stage so the conversation layer records
    # research_failure_engine_capability rather than hiding it as a
    # generic internal error, and never as an unverified backtest result.
    if "unsupportedstrategy" in normalized:
        return ResearchFailure("engine_capability", error_type, False, "영하님, 이 전략은 백테스트 엔진이 아직 해석하지 못하는 규칙을 포함하고 있어 검증을 진행하지 않았습니다. 검증되지 않은 결과는 만들지 않겠습니다.")
    if "backtest" in normalized:
        return ResearchFailure("backtest", error_type, False, "영하님, 백테스트 실행 중 오류가 발생했습니다. 검증되지 않은 성과 수치는 만들지 않겠습니다.")
    return ResearchFailure("tool", error_type, True, "영하님, 연구 도구 실행 중 오류가 발생했습니다. 검증되지 않은 연구 결과는 만들지 않겠습니다.")


def classify_exception(exc: Exception) -> ResearchFailure:
    error_type = exc.__class__.__name__
    message = str(exc)
    if isinstance(exc, ProviderTimeoutError) or "providertimeout" in error_type.casefold():
        return ResearchFailure("llm", error_type, True, "현재 로컬 LLM 응답이 지연되고 있습니다, 영하님. 잠시 후 다시 시도해 주세요.")
    return classify_tool_failure(error_type, message) if _looks_like_research_failure(error_type, message) else ResearchFailure(
        "internal",
        error_type,
        False,
        "영하님, 연구 처리 중 내부 오류가 발생했습니다. 오류는 서버 로그에 기록했고, 검증되지 않은 결과는 만들지 않겠습니다.",
    )


def warning_for_failure(failure: ResearchFailure) -> str:
    return f"research failure: {failure.stage}:{failure.error_type}"


def _looks_like_research_failure(error_type: str, message: str) -> bool:
    normalized = f"{error_type} {message}".casefold()
    return any(token in normalized for token in ("realmarketdataunavailable", "real_data_unavailable", "dataquality", "backtest", "blocking_quality", "unsupportedstrategy"))
