#!/usr/bin/env bash
set -euo pipefail

echo "Stop service, restore the previous reviewed Git tag, validate config/db, then start service."
echo "Run restore dry-run before replacing runtime SQLite backups."
