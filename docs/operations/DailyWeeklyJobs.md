# Daily and Weekly Jobs

Supported dry-run CLI commands:

```bash
python -m gaon.runtime.cli daily-report --date 2026-07-17
python -m gaon.runtime.cli weekly-review --week-start 2026-07-13
python -m gaon.runtime.cli revalidation-scan --at 2026-07-17T00:00:00Z
```

The scheduler is in-memory and deterministic. OS cron/systemd registration is out of scope.

CLI commands default to dry-run. Commands that expose execution flags use explicit mutually exclusive `--dry-run` and `--execute` options. In this phase, `--execute` is parsed for safety testing but external side effects remain unimplemented.
