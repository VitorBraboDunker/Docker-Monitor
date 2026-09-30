#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-separado}"
case "$mode" in separado|unico) ;; *) exit 1;; esac
file="compose.$mode.yaml"
out="$PWD/backups/$(date +%Y%m%d-%H%M%S)-$mode"
mkdir -p "$out";chmod 700 "$out"
if [[ "$mode" == separado ]];then image=grafana/grafana:13.2.2;volumes=(grafana_data prometheus_data alertmanager_data loki_data alloy_data caddy_data)
else image=dunker/monitor-all-in-one:1.1.0;volumes=(monitor_data);fi
for volume in "${volumes[@]}";do docker volume inspect "dunker-${mode}_${volume}" >/dev/null;done
echo 'Parando os serviços para uma cópia consistente...'
docker compose -f "$file" stop
trap 'docker compose -f "$file" up -d --no-build --pull never' EXIT
for volume in "${volumes[@]}";do
 docker run --rm --network none --user 0 --entrypoint tar -v "dunker-${mode}_${volume}:/source:ro" -v "$out:/backup" "$image" -czf "/backup/$volume.tar.gz" -C /source .
done
items=(config)
for item in .env certs inventario.csv ACESSOS-PRIVADOS.txt;do [[ ! -e "$item" ]] || items+=("$item");done
tar -czf "$out/configuracao.tar.gz" "${items[@]}"
chmod 600 "$out"/*.tar.gz
echo "Backup: $out. Contém senhas e a autoridade certificadora; guarde com acesso restrito."
