#!/usr/bin/env bash
# Idempotent setup for the nginx HTTP basic-auth gate referenced (commented
# out by default) in deploy/nginx/strategylab-binance.conf.example. Creates
# /etc/nginx/.htpasswd-strategylab if it doesn't exist yet, then adds/updates
# one user's password in it. Never prints the password back out, and never
# touches an unrelated existing htpasswd file.
#
# Usage: setup_basic_auth.sh <username>
#   Prompts interactively for the password (via `htpasswd`'s own prompt) -
#   never accepts a password as a command-line argument, which would leak it
#   into shell history / process listings.
set -euo pipefail

HTPASSWD_FILE="/etc/nginx/.htpasswd-strategylab"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <username>" >&2
  exit 1
fi
USERNAME="$1"

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root (it writes to /etc/nginx)." >&2
  exit 1
fi

if ! command -v htpasswd &>/dev/null; then
  echo "htpasswd not found. Install it first:" >&2
  echo "  apt install apache2-utils" >&2
  exit 1
fi

if [[ -f "$HTPASSWD_FILE" ]]; then
  echo "$HTPASSWD_FILE already exists - adding/updating user '$USERNAME' in it."
  htpasswd "$HTPASSWD_FILE" "$USERNAME"
else
  echo "Creating $HTPASSWD_FILE with user '$USERNAME'."
  htpasswd -c "$HTPASSWD_FILE" "$USERNAME"
  chmod 640 "$HTPASSWD_FILE"
  chown root:www-data "$HTPASSWD_FILE" 2>/dev/null || true
fi

echo
echo "Done. Now uncomment the two 'auth_basic'/'auth_basic_user_file' line pairs"
echo "in your deployed nginx config (see deploy/nginx/strategylab-binance.conf.example)"
echo "and reload nginx:"
echo "  nginx -t && systemctl reload nginx"
