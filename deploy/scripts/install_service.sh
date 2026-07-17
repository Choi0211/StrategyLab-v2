#!/usr/bin/env bash
set -euo pipefail

echo "Install strategylab-gaon.service as root after creating a non-root strategylab user."
echo "Copy deploy/systemd/strategylab-gaon.service to /etc/systemd/system/."
echo "Copy deploy/systemd/strategylab-gaon.env.example to /etc/strategylab/gaon.env and fill secrets outside Git."
