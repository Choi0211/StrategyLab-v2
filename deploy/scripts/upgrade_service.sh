#!/usr/bin/env bash
# Upgrade an already-installed deployment to a reviewed git ref.
# Backs up the runtime DB BEFORE touching anything else, only restarts
# services if the test/import-path checks pass, and never overwrites
# /etc/strategylab/*.env. Run as the deploy user (needs write access to
# /opt/strategylab-v2 and /var/lib/strategylab/backups) with sudo available
# for the systemctl calls, or as root.
#
# Usage: upgrade_service.sh <git-ref>   (e.g. a reviewed tag or commit SHA)
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <git-ref>" >&2
  exit 1
fi
GIT_REF="$1"

INSTALL_DIR="/opt/strategylab-v2"
DB_PATH="/var/lib/strategylab/gaon-runtime.sqlite"
BACKUPS_DIR="/var/lib/strategylab/backups"
VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"

cd "$INSTALL_DIR"

echo "== 1/6: backing up current DB (before any code change) =="
mkdir -p "$BACKUPS_DIR"
if [[ -f "$DB_PATH" ]]; then
  BACKUP_PATH="$BACKUPS_DIR/gaon-runtime.sqlite.$(date -u +%Y-%m-%dT%H%M%SZ).bak"
  cp "$DB_PATH" "$BACKUP_PATH"
  echo "backed up $DB_PATH -> $BACKUP_PATH"
else
  echo "no existing DB at $DB_PATH yet (first deploy?), nothing to back up"
fi

echo "== 2/6: fetching and checking out $GIT_REF =="
CURRENT_REF="$(git rev-parse --short HEAD)"
git fetch --tags origin
git checkout "$GIT_REF"
echo "checked out $GIT_REF (was at $CURRENT_REF - use rollback_service.sh $CURRENT_REF to undo)"

echo "== 3/6: refreshing editable install =="
"$VENV_PYTHON" -m pip install -e . --quiet

echo "== 4/6: import path check (must load from this checkout, not a stale site-packages copy) =="
"$VENV_PYTHON" -m gaon.runtime.cli deployment-import-path-check --expected-source "$INSTALL_DIR/src/gaon"

echo "== 5/6: full release verification =="
if ! "$VENV_PYTHON" scripts/verify_release.py; then
  echo "release verification FAILED - not restarting any service." >&2
  echo "Fix the failure, or roll back with: deploy/scripts/rollback_service.sh $CURRENT_REF" >&2
  exit 1
fi
echo "release verification passed"

echo "== 6/6: restarting services and health-checking =="
systemctl restart strategylab-gaon.service
systemctl restart gaon-web.service

HEALTH_OK=0
for _ in $(seq 1 10); do
  if curl -sf http://127.0.0.1:8765/gaon/health >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  sleep 2
done

if [[ "$HEALTH_OK" -ne 1 ]]; then
  echo "gaon-web health check failed after restart." >&2
  echo "Investigate with: systemctl status gaon-web.service strategylab-gaon.service" >&2
  echo "Or roll back with: deploy/scripts/rollback_service.sh $CURRENT_REF" >&2
  exit 1
fi

echo "upgrade to $GIT_REF complete, both services restarted, health check passed."
