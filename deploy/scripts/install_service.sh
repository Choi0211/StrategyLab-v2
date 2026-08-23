#!/usr/bin/env bash
# Idempotent first-time install of the strategylab-gaon and gaon-web
# systemd services. Safe to re-run: every step checks current state before
# acting, never overwrites an existing env file (secrets), and backs up an
# existing unit file before replacing it rather than silently clobbering a
# hand-edited one. Must be run as root (it creates a system user, writes to
# /etc and /opt, and calls systemctl).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_DIR="/opt/strategylab-v2"
VAR_DIR="/var/lib/strategylab"
ETC_DIR="/etc/strategylab"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_USER="strategylab"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must be run as root (it creates a system user and writes to /etc, /opt, /var/lib)." >&2
  exit 1
fi

echo "== 1/6: system user/group =="
if id "$SERVICE_USER" &>/dev/null; then
  echo "user '$SERVICE_USER' already exists, skipping"
else
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  echo "created system user '$SERVICE_USER'"
fi

echo "== 2/6: directories =="
for dir in "$INSTALL_DIR" "$VAR_DIR" "$VAR_DIR/backups" "$ETC_DIR"; do
  if [[ -d "$dir" ]]; then
    echo "$dir already exists, skipping"
  else
    mkdir -p "$dir"
    chown "$SERVICE_USER:$SERVICE_USER" "$dir"
    chmod 750 "$dir"
    echo "created $dir"
  fi
done

echo "== 3/6: application code =="
if [[ "$REPO_ROOT" != "$INSTALL_DIR" ]]; then
  echo "NOTE: this script was invoked from $REPO_ROOT, not $INSTALL_DIR."
  echo "It only installs systemd units/env templates below - it does NOT copy"
  echo "application code. Deploy the reviewed release to $INSTALL_DIR yourself"
  echo "(e.g. 'git clone'/'git pull' as the '$SERVICE_USER' user, or however"
  echo "your release process already places code there), then create/refresh"
  echo "the virtualenv at $INSTALL_DIR/.venv with 'pip install -e .'"
else
  echo "running from $INSTALL_DIR, application code is already in place"
fi

echo "== 4/6: systemd unit files (backs up an existing file before replacing) =="
for unit in strategylab-gaon.service gaon-web.service gaon-storage-lifecycle.service gaon-storage-lifecycle.timer; do
  src="$REPO_ROOT/deploy/systemd/$unit"
  dest="$SYSTEMD_DIR/$unit"
  if [[ ! -f "$src" ]]; then
    echo "WARNING: $src not found in this checkout, skipping $unit" >&2
    continue
  fi
  if [[ -f "$dest" ]]; then
    if cmp -s "$src" "$dest"; then
      echo "$dest already up to date, skipping"
    else
      backup="$dest.bak.$(date +%s)"
      cp "$dest" "$backup"
      cp "$src" "$dest"
      echo "$dest differed from the reviewed unit - backed up existing file to $backup and replaced it"
    fi
  else
    cp "$src" "$dest"
    echo "installed $dest"
  fi
done

echo "== 5/6: env files (never overwrites an existing file - these hold secrets) =="
for env_example in strategylab-gaon.env.example gaon-web.env.example; do
  dest_name="${env_example%.example}"
  src="$REPO_ROOT/deploy/systemd/$env_example"
  dest="$ETC_DIR/$dest_name"
  if [[ ! -f "$src" ]]; then
    echo "WARNING: $src not found in this checkout, skipping $dest_name" >&2
    continue
  fi
  if [[ -f "$dest" ]]; then
    echo "$dest already exists, leaving it untouched (fill in real values by hand if you haven't already)"
  else
    cp "$src" "$dest"
    chown "$SERVICE_USER:$SERVICE_USER" "$dest"
    chmod 640 "$dest"
    echo "created $dest from template - EDIT THIS FILE to fill in real secrets before starting the service"
  fi
done

echo "== 6/6: reload systemd =="
systemctl daemon-reload
echo "systemd units reloaded"

cat <<'EOF'

Install script finished. Remaining MANUAL steps (not automated on purpose):

  1. Edit /etc/strategylab/gaon.env and /etc/strategylab/gaon-web.env,
     filling in real secrets (Telegram bot token, approval signing secret,
     any assistant API key). See deploy/docs/secret_migration_checklist.md.
  2. Verify the deployed code imports from the expected path:
       sudo -u strategylab /opt/strategylab-v2/.venv/bin/python -m gaon.runtime.cli \
         deployment-import-path-check --expected-source /opt/strategylab-v2/src/gaon
  3. Enable and start the services:
       systemctl enable --now strategylab-gaon.service
       systemctl enable --now gaon-web.service
       systemctl enable --now gaon-storage-lifecycle.timer
  4. Check status:
       systemctl status strategylab-gaon.service gaon-web.service
       curl -sf http://127.0.0.1:8765/gaon/health
EOF
