#!/usr/bin/env bash
set -euo pipefail

echo "Pull the reviewed release branch, run tests, then restart strategylab-gaon.service."
echo "Do not overwrite /etc/strategylab/gaon.env during upgrade."
