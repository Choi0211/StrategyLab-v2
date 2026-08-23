# Backup retention & failure isolation

This documents two things the master integration plan asks for that are
mostly *properties of the existing design* rather than new code: how backups
avoid growing forever, and why one subsystem crashing can't take another
down. Where something genuinely needed a new artifact, it's cross-referenced
below rather than duplicated.

## Backup retention (Section 13)

**DB backups** (`upgrade_service.sh`, both the StrategyLab-v2 and
binance_ai_bot versions): every upgrade run copies the live DB/state files
into a fresh timestamped directory under `<var-dir>/backups/<timestamp>/`
before touching anything else. Nothing deletes these automatically today -
that's intentional: an upgrade script is the wrong place to also be making
retention decisions about backups an operator may still need for a rollback.
Retention instead happens through the **storage lifecycle manager**
(`deploy/scripts/storage_lifecycle_manager.py`):

- Everything under a `backups/` directory is classified **COLD** regardless
  of age (see the script's own module docstring).
- `--report` (safe to run daily via `gaon-storage-lifecycle.timer`) shows
  how much COLD data has accumulated and flags disk-usage thresholds - it
  never deletes anything itself.
- Actual deletion only happens via `--cleanup <verified-manifest>`, and only
  for files a human/PC-side process has positively confirmed are safely
  archived elsewhere (see `deploy/scripts/storage_lifecycle_manager.py`'s
  own docstring and `binance_ai_bot_2/tools/pc_archive_sync/`). Every
  deletion (and every skip) is appended to a JSON-lines deletion log - this
  is the "manifest/log 남길 것" requirement from the master plan, satisfied
  structurally rather than by a separate log file per backup.

So the actual policy is: **age-based COLD classification + a real archive
(the PC) + an explicit, logged, hash-verified deletion step** - not a bare
"keep last N" counter, which would risk deleting a backup nobody had
actually copied anywhere else yet. If a simpler "keep last N backups
locally regardless of PC archive status" policy is ever wanted in addition,
that would be a deliberate product decision (how many N, and whether it's
safe given the PC may be offline for days) - not something to default to
silently.

**Journal logs**: capped by `deploy/systemd/journald-strategylab.conf`
(`SystemMaxUse=500M`), installed idempotently by `install_service.sh`. This
is the concrete artifact for the master plan's "systemd journal은 현재
500MB 제한 설정이 있으므로 유지 확인" line - rather than trusting that limit
already exists on whatever VPS this gets deployed to, it's now a
version-controlled file that gets (re-)applied on every install run.

## Failure isolation (Section 14)

The master plan requires: a Binance-side failure can't kill StrategyLab,
a Gaon-web failure can't kill Binance execution, a research failure can't
kill live trading, and an archive-sync failure can't block production. This
is true today as a consequence of process/service boundaries already drawn
elsewhere in this work, not something layered on afterward:

| Failure | Why it's isolated |
|---|---|
| `gaon-web.service` crashes | Separate systemd unit from `strategylab-gaon.service` (own `Restart=on-failure` boundary) and from `binance-trading.service`/`binance-dashboard.service` (different `/opt` tree entirely). `dashboard.py`'s `_ask_gaon`/`_get_gaon_json` never raise - a Gaon outage degrades the Binance dashboard's chat/주식 tab to a clear "연결할 수 없어요" message, nothing more. |
| `binance-dashboard.service` crashes | Separate unit from `binance-trading.service` - the actual order-placing loop in `bot.py` keeps running untouched. This was true even before this integration work; the two were already split. |
| Gaon research/candidate work fails or hangs | Runs inside `strategylab-gaon.service`'s own process; a bug there can crash *that* service (systemd restarts it per `Restart=on-failure`), but has no code path into `binance-trading.service` at all - there is no shared process, no shared Python interpreter, no IPC between them beyond the read-only HTTP calls `dashboard.py` makes outward. |
| `binance_ai_bot_2`/`tools/pc_archive_sync` fails, or the PC is off | The PC-side archive client only ever *reads from* a manifest and *writes to* the PC's own local disk - it has no code path that blocks, waits on, or is invoked by anything VPS-side. `storage_lifecycle_manager.py --cleanup` requires a verified manifest to exist; if the PC never produces one, COLD data simply accumulates (flagged by `--report`'s disk-usage warnings) rather than anything on the VPS stalling waiting for the PC. |
| The VPS reboots | Every service has `Restart=on-failure` + `WantedBy=multi-user.target` (once `systemctl enable`'d) - a reboot brings every service back independently, in whatever order systemd/network-online ordering settles on; none of the units in this repo declare a hard dependency on each other (`gaon-web.service` and `strategylab-gaon.service` both just need the DB file and the network, not each other's process). |

The one soft dependency worth naming honestly: `dashboard.py`'s 주식/chat
features *degrade* without `gaon-web.service` running, but never *fail
hard* - this is a deliberate design choice (see `_ask_gaon`/
`_get_gaon_json`'s docstrings), not an accident of how the HTTP calls happen
to behave.
