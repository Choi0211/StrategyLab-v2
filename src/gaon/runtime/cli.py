"""Safe dry-run runtime CLI."""

from __future__ import annotations

import argparse

from gaon.runtime.reports import build_daily_report, build_weekly_review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gaon.runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config-check")
    sub.add_parser("telegram-poll-once").add_argument("--dry-run", action="store_true", default=True)
    sub.add_parser("notion-sync").add_argument("--dry-run", action="store_true", default=True)
    daily = sub.add_parser("daily-report")
    daily.add_argument("--date", required=False, default="2026-07-17")
    weekly = sub.add_parser("weekly-review")
    weekly.add_argument("--week-start", required=False, default="2026-07-13")
    sub.add_parser("revalidation-scan").add_argument("--at", required=False, default="2026-07-17T00:00:00Z")
    args = parser.parse_args(argv)
    if args.command == "daily-report":
        print(build_daily_report(args.date, f"{args.date}T00:00:00Z").to_text())
    elif args.command == "weekly-review":
        print(build_weekly_review(args.week_start, args.week_start, f"{args.week_start}T00:00:00Z").to_text())
    else:
        print(f"{args.command}: dry-run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
