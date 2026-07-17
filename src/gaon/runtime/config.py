"""Environment-backed runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import UTC, timezone, timedelta

from gaon.runtime.errors import ConfigurationError, mask_secret

SUPPORTED_TIMEZONES = ("UTC", "Asia/Seoul")
SUPPORTED_WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
SUPPORTED_MODES = ("dry-run", "execute")


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

    def __repr__(self) -> str:
        return (
            "GaonRuntimeConfig("
            f"mode={self.mode!r}, telegram_enabled={self.telegram_enabled!r}, "
            f"telegram_bot_token={mask_secret(self.telegram_bot_token)!r}, "
            f"telegram_allowed_chat_ids={self.telegram_allowed_chat_ids!r}, "
            f"notion_enabled={self.notion_enabled!r}, notion_token={mask_secret(self.notion_token)!r}, "
            f"timezone={self.timezone!r}, dry_run={self.dry_run!r}, "
            f"approval_signing_secret={mask_secret(self.approval_signing_secret)!r})"
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
