"""Environment-backed runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gaon.runtime.errors import ConfigurationError, mask_secret


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

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"invalid timezone: {self.timezone}") from exc
        for chat_id in self.telegram_allowed_chat_ids:
            if not chat_id or not chat_id.lstrip("-").isdigit():
                raise ConfigurationError("telegram allowed chat IDs must be numeric")
        if self.telegram_enabled and not self.telegram_bot_token:
            raise ConfigurationError("telegram token is required when Telegram is enabled")
        if self.notion_enabled and not self.notion_token:
            raise ConfigurationError("notion token is required when Notion is enabled")
        if not self.dry_run and self.mode != "execute":
            raise ConfigurationError("non-dry-run mode requires explicit execute mode")

    def __repr__(self) -> str:
        return (
            "GaonRuntimeConfig("
            f"mode={self.mode!r}, telegram_enabled={self.telegram_enabled!r}, "
            f"telegram_bot_token={mask_secret(self.telegram_bot_token)!r}, "
            f"telegram_allowed_chat_ids={self.telegram_allowed_chat_ids!r}, "
            f"notion_enabled={self.notion_enabled!r}, notion_token={mask_secret(self.notion_token)!r}, "
            f"timezone={self.timezone!r}, dry_run={self.dry_run!r})"
        )


def load_runtime_config(env: dict[str, str]) -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        mode=env.get("GAON_RUNTIME_MODE", "dry-run"),
        telegram_enabled=_bool(env.get("GAON_TELEGRAM_ENABLED")),
        telegram_bot_token=env.get("GAON_TELEGRAM_BOT_TOKEN"),
        telegram_allowed_chat_ids=_csv(env.get("GAON_TELEGRAM_ALLOWED_CHAT_IDS")),
        notion_enabled=_bool(env.get("GAON_NOTION_ENABLED")),
        notion_token=env.get("GAON_NOTION_TOKEN"),
        notion_parent_page_id=env.get("GAON_NOTION_PARENT_PAGE_ID"),
        notion_research_database_id=env.get("GAON_NOTION_RESEARCH_DATABASE_ID"),
        notion_memory_database_id=env.get("GAON_NOTION_MEMORY_DATABASE_ID"),
        timezone=env.get("GAON_TIMEZONE", "Asia/Seoul"),
        daily_report_time=env.get("GAON_DAILY_REPORT_TIME", "09:00"),
        weekly_report_day=env.get("GAON_WEEKLY_REPORT_DAY", "MONDAY"),
        weekly_report_time=env.get("GAON_WEEKLY_REPORT_TIME", "09:00"),
        dry_run=_bool(env.get("GAON_DRY_RUN", "true")),
    )


def _bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())
