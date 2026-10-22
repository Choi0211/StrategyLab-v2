#!/usr/bin/env bash
# CI/cloud only. No server/system package installation.
set -euo pipefail
cache_dir=$(mktemp -d)
trap 'rm -rf "$cache_dir"' EXIT
curl --fail --silent --show-error --location \
  https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_linux_amd64.tar.gz \
  --output "$cache_dir/actionlint.tar.gz"
printf '%s  %s\n' 023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757 \
  "$cache_dir/actionlint.tar.gz" | sha256sum --check --status
tar -xzf "$cache_dir/actionlint.tar.gz" -C "$cache_dir" actionlint
"$cache_dir/actionlint" .github/workflows/gaon-production.yml .github/workflows/verify.yml
