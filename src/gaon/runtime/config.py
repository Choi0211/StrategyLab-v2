"""Environment-backed runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import UTC, timezone, timedelta

from gaon.runtime.errors import ConfigurationError, mask_secret

SUPPORTED_TIMEZONES = ("UTC", "Asia/Seoul")
SUPPORTED_WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
SUPPORTED_MODES = ("dry-run", "execute")
SUPPORTED_EXECUTION_MODES = ("disabled", "paper", "live")


@dataclass(frozen=True)
class GaonRuntimeConfig:
    mode: str = "dry-run"
    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_allowed_chat_ids: tuple[str, ...] = ()
    notion_enabled: bool = False
    notion_token: str | None = None
    notion_parent_page_id: str | None = None
    notion_research_database_id: str | None = None
    notion_memory_database_id: str | None = None
    timezone: str = "Asia/Seoul"
    daily_report_time: str = "09:00"
    weekly_report_day: str = "MONDAY"
    weekly_report_time: str = "09:00"
    dry_run: bool = True
    approval_signing_secret: str | None = None
    assistant_enabled: bool = False
    assistant_provider: str = "deterministic"
    assistant_api_key: str | None = None
    assistant_base_url: str | None = None
    assistant_model: str | None = None
    assistant_timeout_seconds: float = 10.0
    assistant_max_output_tokens: int = 500
    assistant_max_tool_calls_per_turn: int = 3
    assistant_max_planner_steps: int = 5
    assistant_max_requests_per_minute: int = 12
    assistant_max_context_chars: int = 4000
    free_only_mode: bool = True
    paid_provider_enabled: bool = False
    execution_mode: str = "disabled"
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        validate_mode(self.mode)
        validate_timezone(self.timezone)
        validate_hhmm(self.daily_report_time, "daily_report_time")
        validate_hhmm(self.weekly_report_time, "weekly_report_time")
        validate_weekday(self.weekly_report_day)
        for chat_id in self.telegram_allowed_chat_ids:
            if not chat_id or not chat_id.lstrip("-").isdigit():
                raise ConfigurationError("telegram allowed chat IDs must be numeric")
        if self.telegram_enabled and not self.telegram_bot_token:
            raise ConfigurationError("telegram token is required when Telegram is enabled")
        if self.notion_enabled and not self.notion_token:
            raise ConfigurationError("notion token is required when Notion is enabled")
        if self.mode == "execute" and self.dry_run:
            raise ConfigurationError("execute mode requires GAON_DRY_RUN=false")
        if not self.dry_run and self.mode != "execute":
            raise ConfigurationError("dry_run=false requires execute mode")
        if self.mode == "execute" and not (self.telegram_enabled or self.notion_enabled):
            raise ConfigurationError("execute mode requires at least one integration enabled")
        if self.mode == "execute" and not self.approval_signing_secret:
            raise ConfigurationError("execute mode requires GAON_APPROVAL_SIGNING_SECRET")
        if self.free_only_mode and self.paid_provider_enabled:
            raise ConfigurationError("paid providers cannot be enabled while GAON_FREE_ONLY_MODE=true")
        if self.assistant_max_tool_calls_per_turn < 0 or self.assistant_max_tool_calls_per_turn > 5:
            raise ConfigurationError("assistant_max_tool_calls_per_turn must be between 0 and 5")
        if self.assistant_max_planner_steps < 1 or self.assistant_max_planner_steps > 8:
            raise ConfigurationError("assistant_max_planner_steps must be between 1 and 8")
        if self.assistant_max_requests_per_minute < 1 or self.assistant_max_requests_per_minute > 60:
            raise ConfigurationError("assistant_max_requests_per_minute must be between 1 and 60")
        if self.assistant_max_context_chars < 500 or self.assistant_max_context_chars > 12000:
            raise ConfigurationError("assistant_max_context_chars must be between 500 and 12000")
        if self.execution_mode not in SUPPORTED_EXECUTION_MODES:
            raise ConfigurationError("execution_mode must be disabled, paper, or live")
        if self.live_trading_enabled and self.execution_mode != "live":
            raise ConfigurationError("live trading can only be enabled when GAON_EXECUTION_MODE=live")

    def __repr__(self) -> str:
        return (
            "GaonRuntimeConfig("
            f"mode={self.mode!r}, telegram_enabled={self.telegram_enabled!r}, "
            f"telegram_bot_token={mask_secret(self.telegram_bot_token)!r}, "
            f"telegram_allowed_chat_ids={self.telegram_allowed_chat_ids!r}, "
            f"notion_enabled={self.notion_enabled!r}, notion_token={mask_secret(self.notion_token)!r}, "
            f"timezone={self.timezone!r}, dry_run={self.dry_run!r}, "
            f"approval_signing_secret={mask_secret(self.approval_signing_secret)!r}, "
            f"assistant_enabled={self.assistant_enabled!r}, assistant_provider={self.assistant_provider!r}, "
            f"assistant_api_key={mask_secret(self.assistant_api_key)!r}, "
            f"free_only_mode={self.free_only_mode!r}, paid_provider_enabled={self.paid_provider_enabled!r}, "
            f"execution_mode={self.execution_mode!r}, live_trading_enabled={self.live_trading_enabled!r})"
        )


def load_runtime_config(env: dict[str, str]) -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        mode=env.get("GAON_RUNTIME_MODE", "dry-run"),
        telegram_enabled=parse_bool(env.get("GAON_TELEGRAM_ENABLED"), "GAON_TELEGRAM_ENABLED", default=False),
        telegram_bot_token=env.get("GAON_TELEGRAM_BOT_TOKEN"),
        telegram_allowed_chat_ids=_csv(env.get("GAON_TELEGRAM_ALLOWED_CHAT_IDS")),
        notion_enabled=parse_bool(env.get("GAON_NOTION_ENABLED"), "GAON_NOTION_ENABLED", default=False),
        notion_token=env.get("GAON_NOTION_TOKEN"),
        notion_parent_page_id=env.get("GAON_NOTION_PARENT_PAGE_ID"),
        notion_research_database_id=env.get("GAON_NOTION_RESEARCH_DATABASE_ID"),
        notion_memory_database_id=env.get("GAON_NOTION_MEMORY_DATABASE_ID"),
        timezone=env.get("GAON_TIMEZONE", "Asia/Seoul"),
        daily_report_time=env.get("GAON_DAILY_REPORT_TIME", "09:00"),
        weekly_report_day=env.get("GAON_WEEKLY_REPORT_DAY", "MONDAY"),
        weekly_report_time=env.get("GAON_WEEKLY_REPORT_TIME", "09:00"),
        dry_run=parse_bool(env.get("GAON_DRY_RUN"), "GAON_DRY_RUN", default=True),
        approval_signing_secret=env.get("GAON_APPROVAL_SIGNING_SECRET"),
        assistant_enabled=parse_bool(env.get("GAON_ASSISTANT_ENABLED"), "GAON_ASSISTANT_ENABLED", default=False),
        assistant_provider=env.get("GAON_ASSISTANT_PROVIDER", "deterministic"),
        assistant_api_key=env.get("GAON_ASSISTANT_API_KEY"),
        assistant_base_url=env.get("GAON_ASSISTANT_BASE_URL"),
        assistant_model=env.get("GAON_ASSISTANT_MODEL"),
        assistant_timeout_seconds=float(env.get("GAON_ASSISTANT_TIMEOUT_SECONDS", "10")),
        assistant_max_output_tokens=int(env.get("GAON_ASSISTANT_MAX_OUTPUT_TOKENS", "500")),
        assistant_max_tool_calls_per_turn=int(env.get("GAON_ASSISTANT_MAX_TOOL_CALLS_PER_TURN", "3")),
        assistant_max_planner_steps=int(env.get("GAON_ASSISTANT_MAX_PLANNER_STEPS", "5")),
        assistant_max_requests_per_minute=int(env.get("GAON_ASSISTANT_MAX_REQUESTS_PER_MINUTE", "12")),
        assistant_max_context_chars=int(env.get("GAON_ASSISTANT_MAX_CONTEXT_CHARS", "4000")),
        free_only_mode=parse_bool(env.get("GAON_FREE_ONLY_MODE"), "GAON_FREE_ONLY_MODE", default=True),
        paid_provider_enabled=parse_bool(env.get("GAON_PAID_PROVIDER_ENABLED"), "GAON_PAID_PROVIDER_ENABLED", default=False),
        execution_mode=env.get("GAON_EXECUTION_MODE", "disabled"),
        live_trading_enabled=parse_bool(env.get("GAON_LIVE_TRADING_ENABLED"), "GAON_LIVE_TRADING_ENABLED", default=False),
    )


def parse_bool(value: str | None, field: str, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{field} must be a boolean")


def validate_timezone(value: str) -> None:
    if value not in SUPPORTED_TIMEZONES:
        raise ConfigurationError(f"unsupported timezone: {value}")


def timezone_for(value: str) -> timezone:
    validate_timezone(value)
    if value == "UTC":
        return UTC
    return timezone(timedelta(hours=9), name="Asia/Seoul")


def validate_mode(value: str) -> None:
    if value not in SUPPORTED_MODES:
        raise ConfigurationError("mode must be dry-run or execute")


def validate_hhmm(value: str, field: str) -> None:
    if re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", value) is None:
        raise ConfigurationError(f"{field} must use HH:MM format")
    hour = int(value[:2])
    if hour > 23:
        raise ConfigurationError(f"{field} hour must be between 00 and 23")


def validate_weekday(value: str) -> None:
    if value.upper() not in SUPPORTED_WEEKDAYS:
        raise ConfigurationError("weekly_report_day must be a valid weekday")


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())
