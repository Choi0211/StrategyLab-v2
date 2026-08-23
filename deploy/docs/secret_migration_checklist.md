# Secret migration checklist

Every secret this deployment needs, and exactly where it goes. None of
these belong in git, in nginx config, in a systemd unit file itself (only
in the `EnvironmentFile` it references), or in any log line.

| Secret | Goes in | Used by |
|---|---|---|
| Telegram bot token | `/etc/strategylab/gaon.env` as `GAON_TELEGRAM_BOT_TOKEN` | `strategylab-gaon.service` |
| Telegram allowed chat IDs (not secret, but keep alongside) | `/etc/strategylab/gaon.env` as `GAON_TELEGRAM_ALLOWED_CHAT_IDS` | `strategylab-gaon.service` |
| Approval signing secret (gates human-approval tokens - treat as highly sensitive, rotating this invalidates all pending approval links) | `/etc/strategylab/gaon.env` as `GAON_APPROVAL_SIGNING_SECRET` | `strategylab-gaon.service`, `gaon-web.service` |
| Assistant/LLM API key (only if `GAON_ASSISTANT_PROVIDER` is not `deterministic`) | `/etc/strategylab/gaon.env` as `GAON_ASSISTANT_API_KEY` | `strategylab-gaon.service`, `gaon-web.service` |
| Binance API key/secret (testnet or real) | the separate `binance_ai_bot` deployment's own env file (see that repo's deploy docs, NOT this repo - this repo never touches Binance credentials) | `bot.py` only |

## Checklist before going live

- [ ] Every file above has real permissions `640` or tighter, owned by the
      `strategylab` service user, not world-readable.
      `ls -l /etc/strategylab/*.env` should show `-rw-r-----`.
- [ ] `git status` in this repo shows no `.env` file staged - `.env`,
      `*.env` (except `*.env.example`) should already be in `.gitignore`;
      confirm rather than assume.
- [ ] No secret value appears in `journalctl -u strategylab-gaon.service`
      or `journalctl -u gaon-web.service` output - the code never echoes
      env values, but double-check after first start.
- [ ] The reverse-proxy config (nginx) does not log full request bodies
      (default nginx access log does not include POST bodies, so this is
      usually fine by default - just don't add `proxy_pass` debug logging
      that would).
- [ ] Binance API key permissions are minimized: **withdrawal permission
      disabled**, IP-restricted if the exchange supports it. This is
      configured on the exchange side, not in any file here - just confirm
      it before considering the migration complete.
- [ ] Rotate any secret that was ever pasted into a chat log, a shared
      document, or committed to git history (even briefly) - deleting a
      file from a later commit does not remove it from history.
