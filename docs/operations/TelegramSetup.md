# Telegram Setup

This phase provides dry-run Telegram contracts only.

For future real use:

- provide token through `GAON_TELEGRAM_BOT_TOKEN`
- set `GAON_TELEGRAM_ENABLED=true`
- set allowed chat IDs through `GAON_TELEGRAM_ALLOWED_CHAT_IDS`
- keep `GAON_DRY_RUN=true` until explicitly testing execution

Telegram commands cannot approve, trade, run shell commands, or mutate repositories.
