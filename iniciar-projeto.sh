#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
docker compose -f compose.separado.yaml up -d --no-build
docker compose -f compose.separado.yaml ps
