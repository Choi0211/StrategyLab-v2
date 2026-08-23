#!/usr/bin/env bash
# Roll back to a previous git ref and, optionally, restore the DB backup
# taken by upgrade_service.sh just before the upgrade that's being undone.
# Defaults to the MOST RECENT backup file; pass an explicit filename to
# restore a different one. Supports --dry-run, which prints every action
# it would take (including which backup file it would restore) without
# stopping services, checking out anything, or touching the DB.
#
# Usage: rollback_service.sh [--dry-run] <git-ref> [backup-filename]
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 [--dry-run] <git-ref> [backup-filename]" >&2
  exit 1
fi
GIT_REF="$1"
EXPLICIT_BACKUP="${2:-}"

INSTALL_DIR="/opt/strategylab-v2"
DB_PATH="/var/lib/strategylab/gaon-runtime.sqlite"
BACKUPS_DIR="/var/lib/strategylab/backups"
VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"

cd "$INSTALL_DIR"

if [[ -n "$EXPLICIT_BACKUP" ]]; then
  RESTORE_FROM="$BACKUPS_DIR/$EXPLICIT_BACKUP"
else
  RESTORE_FROM="$(ls -t "$BACKUPS_DIR"/gaon-runtime.sqlite.*.bak 2>/dev/null | head -n1 || true)"
fi

echo "== rollback plan =="
echo "  target git ref:  $GIT_REF"
echo "  DB restore from: ${RESTORE_FROM:-<no backup found, DB will NOT be touched>}"
echo "  mode:            $([[ $DRY_RUN -eq 1 ]] && echo 'DRY RUN - no changes will be made' || echo 'LIVE')"
echo ""

if [[ -n "$RESTORE_FROM" && ! -f "$RESTORE_FROM" ]]; then
  echo "ERROR: backup file not found: $RESTORE_FROM" >&2
  exit 1
fi

if [[ $DRY_RUN -eq 1 ]]; then
  echo "-- dry run: would stop strategylab-gaon.service and gaon-web.service --"
  echo "-- dry run: would run 'git checkout $GIT_REF' in $INSTALL_DIR --"
  if [[ -n "$RESTORE_FROM" ]]; then
    echo "-- dry run: would copy $RESTORE_FROM -> $DB_PATH (current DB, if any, would first be saved as ${DB_PATH}.pre-rollback.$(date -u +%Y-%m-%dT%H%M%SZ)) --"
  fi
  echo "-- dry run: would refresh editable install and restart both services --"
  echo "-- dry run: would poll GET http://127.0.0.1:8765/gaon/health --"
  echo ""
  echo "Nothing was changed. Re-run without --dry-run to actually perform this rollback."
  exit 0
fi

echo "== 1/6: stopping services =="
systemctl stop gaon-web.service strategylab-gaon.service

echo "== 2/6: checking out $GIT_REF =="
CURRENT_REF="$(git rev-parse --short HEAD)"
git checkout "$GIT_REF"
echo "checked out $GIT_REF (was at $CURRENT_REF)"

if [[ -n "$RESTORE_FROM" ]]; then
  echo "== 3/6: restoring DB backup =="
  if [[ -f "$DB_PATH" ]]; then
    PRE_ROLLBACK_SAVE="${DB_PATH}.pre-rollback.$(date -u +%Y-%m-%dT%H%M%SZ)"
    cp "$DB_PATH" "$PRE_ROLLBACK_SAVE"
    echo "saved current DB to $PRE_ROLLBACK_SAVE before overwriting"
  fi
  cp "$RESTORE_FROM" "$DB_PATH"
  echo "restored DB from $RESTORE_FROM"
else
  echo "== 3/6: no DB backup found, leaving current DB untouched =="
fi

echo "== 4/6: refreshing editable install =="
"$VENV_PYTHON" -m pip install -e . --quiet

echo "== 5/6: restarting services =="
systemctl start strategylab-gaon.service
systemctl start gaon-web.service

echo "== 6/6: health check =="
HEALTH_OK=0
for _ in $(seq 1 10); do
  if curl -sf http://127.0.0.1:8765/gaon/health >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  sleep 2
done

if [[ "$HEALTH_OK" -ne 1 ]]; then
  echo "gaon-web health check failed after rollback - investigate manually:" >&2
  echo "  systemctl status gaon-web.service strategylab-gaon.service" >&2
  exit 1
fi

echo "rollback to $GIT_REF complete, both services restarted, health check passed."
