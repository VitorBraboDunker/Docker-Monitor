#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-separado}"
case "$mode" in separado|unico) ;; *) echo 'Use: bash scripts/iniciar.sh separado|unico [IP_DA_VM]';exit 1;; esac
[[ "$(uname -m)" == x86_64 ]] || { echo 'Imagens fornecidas: Linux x86-64.';exit 1; }
command -v docker >/dev/null || { echo 'Instale Docker: sudo bash scripts/instalar-docker-ubuntu.sh';exit 1; }
docker compose version >/dev/null
docker info >/dev/null
if [[ -n "${2:-}" ]];then python3 scripts/preparar.py --host "$2";else python3 scripts/preparar.py;fi
other=unico;[[ "$mode" == unico ]] && other=separado
if [[ -n "$(docker ps -q --filter "label=com.docker.compose.project=dunker-$other")" ]];then echo "Pare a outra opção: sudo bash scripts/parar.sh $other";exit 1;fi
file="compose.$mode.yaml";missing=0
while IFS= read -r ref;do docker image inspect "$ref" >/dev/null 2>&1 || missing=1;done < <(docker compose -f "$file" config --images)
if ((missing));then
 archive="../dunker-monitor-${mode}-linux-amd64.tar.gz"
 if compgen -G "../dunker-${mode}-*.part" >/dev/null;then python3 scripts/reconstituir-imagem.py "$mode";fi
 if [[ -f "$archive" ]];then docker load -i "$archive"
 else
  echo 'Sem arquivo local de imagens. Baixando/reconstruindo pela internet...'
  if [[ "$mode" == separado ]];then docker compose -f "$file" pull --ignore-buildable;docker compose -f "$file" build ping admin
  else docker compose -f "$file" build monitor;fi
 fi
fi
docker compose -f "$file" config --quiet
docker compose -f "$file" up -d --no-build --pull never
python3 scripts/verificar.py
printf '%s\n' 'Acesso HTTP pela porta ACCESS_PORT do .env. Cadastro: /monitoramento/' 'Login: admin, senha inicial em config/secrets/grafana_admin_password'
