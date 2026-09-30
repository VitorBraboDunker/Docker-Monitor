#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-separado}"
case "$mode" in separado|unico) ;; *) exit 1;; esac
docker compose -f "compose.$mode.yaml" stop
echo 'Serviços parados; volumes preservados.'
