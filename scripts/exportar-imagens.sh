#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-separado}"
case "$mode" in separado|unico) ;; *) exit 1;; esac
mapfile -t images < <(docker compose -f "compose.$mode.yaml" config --images | sort -u)
output="../dunker-monitor-${mode}-linux-amd64.tar.gz"
[[ ! -e "$output" ]] || { echo "Arquivo já existe: $output";exit 1; }
docker image save "${images[@]}" | gzip -3 > "$output"
sha256sum "$output" > "$output.sha256"
echo "Exportado: $output"
