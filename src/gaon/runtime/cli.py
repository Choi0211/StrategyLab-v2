"""Safe runtime CLI."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
import sys
from typing import Any

from gaon.integrations.telegram.client import TelegramBotApiClient
from gaon.integrations.telegram.contracts import TelegramClient, TelegramDiscoveredChat, TelegramPollResult
from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import discover_private_chats, parse_update_result
from gaon.runtime.config import GaonRuntimeConfig, load_runtime_config
from gaon.runtime.conversation import ConversationRuntime
from gaon.runtime.errors import ConfigurationError, GaonRuntimeError
from gaon.runtime.reports import build_daily_report, build_weekly_review

TELEGRAM_SMOKE_TEXT = "Gaon Telegram 연결 테스트가 성공했습니다."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gaon.runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config-check")
    _add_dry_run_flags(sub.add_parser("telegram-get-me"))
    _add_dry_run_flags(sub.add_parser("telegram-discover-chat"))
    poll = sub.add_parser("telegram-poll-once")
    poll.add_argument("--offset", type=int, required=False)
    _add_dry_run_flags(poll)
    smoke = sub.add_parser("telegram-send-smoke")
    smoke.add_argument("--chat-id", required=True)
    _add_dry_run_flags(smoke)
    _add_dry_run_flags(sub.add_parser("notion-sync"))
    daily = sub.add_parser("daily-report")
    daily.add_argument("--date", required=False, default="2026-07-17")
    _add_dry_run_flags(daily)
    weekly = sub.add_parser("weekly-review")
    weekly.add_argument("--week-start", required=False, default="2026-07-13")
    _add_dry_run_flags(weekly)
    revalidation = sub.add_parser("revalidation-scan")
    revalidation.add_argument("--at", required=False, default="2026-07-17T00:00:00Z")
    _add_dry_run_flags(revalidation)
    args = parser.parse_args(argv)

    try:
        return _run(args)
    except GaonRuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.command == "config-check":
        print(load_runtime_config(os.environ).__repr__())
    elif args.command == "daily-report":
        print(build_daily_report(args.date, f"{args.date}T00:00:00Z").to_text())
    elif args.command == "weekly-review":
        print(build_weekly_review(args.week_start, args.week_start, f"{args.week_start}T00:00:00Z").to_text())
    elif args.command == "telegram-get-me":
        if args.dry_run:
            print("telegram-get-me: dry-run")
        else:
            config = _load_execute_config(require_allowed_chat_ids=False)
            _print_bot_info(_telegram_client(config).get_me())
    elif args.command == "telegram-discover-chat":
        if args.dry_run:
            print("telegram-discover-chat: dry-run")
        else:
            config = _load_execute_config(require_allowed_chat_ids=False)
            chats = discover_chats(_telegram_client(config), received_at=_utc_now())
            _print_discovered_chats(chats)
    elif args.command == "telegram-send-smoke":
        if args.dry_run:
            print("telegram-send-smoke: dry-run")
        else:
            config = _load_execute_config(require_allowed_chat_ids=True)
            response = send_smoke(_telegram_client(config), config, args.chat_id)
            print(f"telegram-send-smoke: sent message_id={response.message_id or 'unknown'}")
    elif args.command == "telegram-poll-once":
        if args.dry_run:
            print("telegram-poll-once: dry-run")
        else:
            config = _load_execute_config(require_allowed_chat_ids=True)
            results = poll_once(_telegram_client(config), config, offset=args.offset, received_at=_utc_now())
            _print_poll_results(results)
    else:
        mode = "dry-run" if getattr(args, "dry_run", True) else "execute requested but not implemented"
        print(f"{args.command}: {mode}")
    return 0


def discover_chats(client: Any, *, received_at: str) -> tuple[TelegramDiscoveredChat, ...]:
    updates = client.get_updates(timeout=0, limit=100)
    return discover_private_chats(updates, received_at=received_at)


def poll_once(client: Any, config: GaonRuntimeConfig, *, offset: int | None, received_at: str) -> tuple[TelegramPollResult, ...]:
    updates = client.get_updates(offset=offset, timeout=0, limit=100)
    runtime = TelegramRuntime(ConversationRuntime(), allowed_chat_ids=config.telegram_allowed_chat_ids)
    results: list[TelegramPollResult] = []
    for payload in updates:
        update = parse_update_result(payload, received_at=received_at)
        results.append(process_update(update, runtime, client))
    return tuple(results)


def send_smoke(client: TelegramClient, config: GaonRuntimeConfig, chat_id: str):
    if chat_id not in config.telegram_allowed_chat_ids:
        raise ConfigurationError("telegram-send-smoke chat-id must be in GAON_TELEGRAM_ALLOWED_CHAT_IDS")
    return client.send_message(chat_id, TELEGRAM_SMOKE_TEXT)


def _load_execute_config(*, require_allowed_chat_ids: bool) -> GaonRuntimeConfig:
    config = load_runtime_config(os.environ)
    if config.mode != "execute" or config.dry_run:
        raise ConfigurationError("execute requires GAON_RUNTIME_MODE=execute and GAON_DRY_RUN=false")
    if not config.telegram_enabled or not config.telegram_bot_token:
        raise ConfigurationError("execute requires GAON_TELEGRAM_ENABLED=true and GAON_TELEGRAM_BOT_TOKEN")
    if require_allowed_chat_ids and not config.telegram_allowed_chat_ids:
        raise ConfigurationError("message execution requires GAON_TELEGRAM_ALLOWED_CHAT_IDS")
    return config


def _telegram_client(config: GaonRuntimeConfig) -> TelegramBotApiClient:
    if not config.telegram_bot_token:
        raise ConfigurationError("telegram token is required")
    return TelegramBotApiClient(config.telegram_bot_token)


def _print_bot_info(info: dict) -> None:
    print(f"bot id: {info.get('id', 'unknown')}")
    print(f"username: {info.get('username', 'unknown')}")
    print(f"first name: {info.get('first_name', 'unknown')}")
    if "can_join_groups" in info:
        print(f"can_join_groups: {info['can_join_groups']}")


def _print_discovered_chats(chats: tuple[TelegramDiscoveredChat, ...]) -> None:
    if not chats:
        print("No private chat found. Send a message to the bot and run this command again.")
        return
    for chat in chats:
        print(f"chat_id={chat.chat_id} chat_type={chat.chat_type} username={chat.username or ''} first_name={chat.first_name or ''} preview={chat.message_preview}")


def _print_poll_results(results: tuple[TelegramPollResult, ...]) -> None:
    if not results:
        print("telegram-poll-once: no updates")
        return
    for result in results:
        print(f"update_id={result.update_id} next_offset={result.next_offset} status={result.status} chat_id={result.chat_id or ''}")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _add_dry_run_flags(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", help="prepare output without external side effects")
    mode.add_argument("--execute", dest="dry_run", action="store_false", help="request execution after all production gates pass")
    parser.set_defaults(dry_run=True)


if __name__ == "__main__":
    raise SystemExit(main())
