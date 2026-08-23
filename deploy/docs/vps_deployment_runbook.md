# VPS deployment runbook (Sections 17 + 18)

Everything below is a **runbook for a human to execute manually, later,
after final review** - nothing in this repository runs any of these commands
automatically. This file exists so the exact sequence is written down once,
in order, rather than reconstructed from scattered script comments at
deploy time.

Two independent deployments are involved: StrategyLab-v2/Gaon at
`/opt/strategylab-v2`, and the Binance bot at `/opt/binance-trading` (a
separate repository, `binance_ai_bot`, with its own `deploy/` directory -
see that repo for its own install/upgrade/rollback scripts, which mirror
this one's conventions).

## 1. Pre-deployment

- [ ] Both repos' `feature/...`/working branches have been reviewed
      (independent code review - see the master task's final report for
      what was reviewed and by whom) and all tests pass:
      `python scripts/verify_release.py` (StrategyLab-v2) and the
      equivalent syntax/self-test checks documented in `binance_ai_bot`'s
      own `deploy/` (that repo currently has no automated test suite -
      `deploy/scripts/upgrade_service.sh` there runs a plain `py_compile`
      sweep as the floor gate).
- [ ] Take a full VPS-level backup/snapshot before touching anything, if
      your hosting provider offers one (separate from the app-level backups
      `upgrade_service.sh` makes) - this is the "backup-before-deploy"
      requirement for the *first* deploy onto a given VPS, where there may
      be nothing yet for the app-level scripts to back up.
- [ ] Confirm you are deploying a specific, reviewed git ref (tag or commit
      SHA) - never `main`/`master` floating.

## 2. StrategyLab-v2 / Gaon - first-time install

```bash
# As a user with sudo, on the VPS:
git clone <your-reviewed-fork-or-remote> /tmp/strategylab-v2-checkout
sudo /tmp/strategylab-v2-checkout/deploy/scripts/install_service.sh
# Follow the printed manual steps: place code at /opt/strategylab-v2,
# create the venv, fill in /etc/strategylab/*.env secrets (see
# deploy/docs/secret_migration_checklist.md), then:
sudo -u strategylab /opt/strategylab-v2/.venv/bin/python -m gaon.runtime.cli \
  deployment-import-path-check --expected-source /opt/strategylab-v2/src/gaon
sudo systemctl enable --now strategylab-gaon.service
sudo systemctl enable --now gaon-web.service
sudo systemctl enable --now gaon-storage-lifecycle.timer
sudo systemctl restart systemd-journald   # applies the 500M journal cap
sudo systemctl status strategylab-gaon.service gaon-web.service
curl -sf http://127.0.0.1:8765/gaon/health
curl -sf http://127.0.0.1:8765/gaon/storage/status
```

## 3. Binance bot - first-time install

See `binance_ai_bot/deploy/scripts/install_service.sh` (same pattern,
different service names: `binance-trading.service`,
`binance-dashboard.service`, `/opt/binance-trading`,
`/etc/binance-trading/bot.env`). **Leave `BINANCE_USE_TESTNET=true`** until
every other step here is done and you've watched it run safely - see that
repo's `deploy/docs/secret_migration_checklist.md`.

```bash
sudo /opt/binance-trading/deploy/scripts/install_service.sh
# fill in /etc/binance-trading/bot.env, create the venv, then:
sudo systemctl enable --now binance-trading.service
sudo systemctl enable --now binance-dashboard.service
curl -sf http://127.0.0.1:5000/api/status
```

## 4. Reverse proxy + HTTPS + auth

Follow `deploy/docs/https_setup.md` end to end (nginx config from
`deploy/nginx/strategylab-binance.conf.example`, certbot, then
`deploy/scripts/setup_basic_auth.sh <username>` and uncomment the
`auth_basic` lines). Verify:

```bash
curl -sf https://<YOUR_DOMAIN>/gaon/health
curl -u <username> https://<YOUR_DOMAIN>/   # should prompt for/accept the password
```

## 5. Upgrading later

```bash
# StrategyLab-v2:
sudo /opt/strategylab-v2/deploy/scripts/upgrade_service.sh <git-ref>
# Binance bot:
sudo /opt/binance-trading/deploy/scripts/upgrade_service.sh <git-ref>
```
Both back up state before touching code and refuse to restart anything if
their safety check fails - read the script output either way.

## 6. Rollback

```bash
sudo /opt/strategylab-v2/deploy/scripts/rollback_service.sh <previous-ref> --dry-run   # review first
sudo /opt/strategylab-v2/deploy/scripts/rollback_service.sh <previous-ref>
# same pattern for /opt/binance-trading/deploy/scripts/rollback_service.sh
```

## 7. PC Archive Sync (once storage actually needs archiving)

On the VPS, generate a manifest of what's currently COLD:
```bash
sudo /opt/strategylab-v2/deploy/scripts/storage_lifecycle_manager.py \
  --build-cold-manifest /var/lib/strategylab/backups/cold-manifest.json
```
Get that manifest to the PC (scp, or expose it via the reverse proxy behind
auth - your choice, not prescribed here). On the PC (Windows), fill in your
own local paths for `<PC_ARCHIVE_SYNC_CHECKOUT>` (where you cloned
`binance_ai_bot_2`) and `<PC_ARCHIVE_DIR>` (wherever you want the archive
kept):
```powershell
python <PC_ARCHIVE_SYNC_CHECKOUT>\tools\pc_archive_sync\archive_sync.py `
  --manifest <path-or-url-to-cold-manifest.json> `
  --archive-dir <PC_ARCHIVE_DIR> `
  --verified-manifest-out <PC_ARCHIVE_DIR>\verified-manifest.json
```
Copy `verified-manifest.json` back to the VPS, then, as a **separate,
deliberate** step (never automatic):
```bash
sudo /opt/strategylab-v2/deploy/scripts/storage_lifecycle_manager.py \
  --cleanup /path/to/verified-manifest.json --dry-run   # review first
sudo /opt/strategylab-v2/deploy/scripts/storage_lifecycle_manager.py \
  --cleanup /path/to/verified-manifest.json
```
See `deploy/scripts/register_task.ps1` (or the manual Task Scheduler steps
documented alongside it in `binance_ai_bot_2/tools/pc_archive_sync/`, if
present) to run the PC-side half of this automatically on PC startup rather
than by hand every time.

## 8. PC-OFF acceptance test (Section 18)

The actual acceptance bar: with the Windows PC **fully powered off**,
from a phone on mobile data (not the home network, to rule out anything
LAN-only):

- [ ] **A. Telegram**: message the Gaon bot, get a real response.
- [ ] **B. Mobile web**: `https://<YOUR_DOMAIN>/` loads over HTTPS, prompts
      for the basic-auth credential if configured, and the page renders
      without horizontal scroll on a phone-width viewport.
- [ ] **C. Web chat**: ask "가온아 현재 바이낸스 상태 알려줘" in the
      dashboard's chat widget, get a real response (not a "연결할 수
      없어요" fallback - that specific failure would mean `gaon-web.service`
      or the reverse-proxy route to it is down).
- [ ] **D. 주식 tab**: Research Mission status renders (or an honest empty
      state if no mission has been started under the relevant session).
- [ ] **E. Binance tab**: balance/position/Champion strategy display
      correctly.
- [ ] **F. Strategy proposal**: confirm a pending proposal (if any) is NOT
      auto-applied - `strategy_params.json` on the VPS must be unchanged
      until someone explicitly presses the approve button.
- [ ] **G. Binance bot**: `systemctl status binance-trading.service` shows
      it's been running continuously - it was never dependent on the PC.
- [ ] **H. Gaon**: `systemctl status strategylab-gaon.service
      gaon-web.service` likewise.
- [ ] **I. PC powered back on**: the archive-sync scheduled task (Task
      Scheduler) runs automatically, downloads any pending COLD manifest,
      verifies SHA-256, finalizes into the local archive, and produces a
      verified manifest - confirm via the client's own printed summary or
      log, then (separately, manually) run the VPS-side `--cleanup` and
      confirm the deletion log records exactly what was removed.

This checklist has **not been executed** as part of this work - it requires
a real VPS, a real domain, and a real phone, none of which exist in this
development environment. It's provided so the user can run it themselves
once actual deployment happens, and should be treated as the true
definition of "done" for this whole integration effort - passing tests
locally is necessary but not sufficient.
