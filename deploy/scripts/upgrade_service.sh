#!/usr/bin/env bash
set -euo pipefail

echo "Pull the reviewed release branch, refresh editable install with .venv/bin/pip install -e ., run tests, verify import path, then restart strategylab-gaon.service."
echo "Do not overwrite /etc/strategylab/gaon.env during upgrade."
echo "Required check: .venv/bin/python -m gaon.runtime.cli deployment-import-path-check --expected-source /opt/strategylab-v2/src/gaon"
