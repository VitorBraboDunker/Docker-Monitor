#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then echo 'Uso: bash atualizar-projeto.sh /opt/dunker-monitor [--nova-instalacao|--somente-verificar]' >&2; exit 1; fi
package=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
project_arg=$1;mode=${2:-}
case "$mode" in ''|--nova-instalacao|--somente-verificar) ;; *) echo 'Opção desconhecida.' >&2;exit 1;; esac
if [[ "$mode" == '--nova-instalacao' ]]; then mkdir -p -- "$project_arg";chmod 700 -- "$project_arg";fi
project=$(cd -- "$project_arg" && pwd -P)
if [[ "$mode" != '--somente-verificar' && "$project" == "$package" ]]; then echo 'Extraia o ZIP em outra pasta; o primeiro argumento aponta para a instalação.' >&2;exit 1;fi
command -v python3 >/dev/null || { echo 'Python 3 é necessário para revisar o Docker no Ubuntu.' >&2;exit 1; }
[[ $(docker info --format '{{.OSType}}') == linux ]] || { echo 'Docker Linux precisa estar disponível.' >&2;exit 1; }
report_relative="diagnostico/revisao-$(date +%Y%m%d-%H%M%S)-$RANDOM"
report="$project/$report_relative";mkdir -p -- "$report"
manager(){ docker run --rm --entrypoint python3 --mount "type=bind,source=$project,target=/projeto" --mount "type=bind,source=$package,target=/pacote,readonly" vitorbrabodunker/dunker-monitor-separado:1.2.0 /pacote/scripts/project_manager.py "$@" --project /projeto --package /pacote; }
python3 "$package/scripts/docker_audit.py" --project "$project" --output "$report" --stage antes
manager inspect --output "/projeto/$report_relative" --stage antes
if [[ "$mode" == '--somente-verificar' ]]; then echo "Revisão concluída: $report";exit 0;fi
python3 "$package/scripts/docker_audit.py" --project "$project" --output "$report" --stage antes --check
args=(apply)
if [[ "$mode" == '--nova-instalacao' ]]; then args+=(--new);fi
compose_name=$(cat "$report/compose-project-name.txt")
if [[ -n "$compose_name" ]]; then args+=(--compose-name "$compose_name");fi
manager "${args[@]}"
cd -- "$project"
validate(){
 if [[ -f config/secrets/ingest_hash.pending ]]; then
  ingest_password=$(<config/secrets/ingest_password)
  docker run --rm --entrypoint caddy caddy:2.11.4 hash-password --plaintext "$ingest_password" > config/secrets/ingest_hash
  unset ingest_password;chmod 600 config/secrets/ingest_hash
  manager finalize-hash
 fi
 docker compose -f compose.separado.yaml config --quiet
 docker compose -f compose.separado.yaml run --rm --no-deps --entrypoint /bin/promtool prometheus check config /etc/dunker/prometheus/separado.yml
 docker compose -f compose.separado.yaml run --rm --no-deps --entrypoint /bin/promtool sharepoint-prometheus check config /etc/dunker/sharepoint/prometheus.yml
 docker compose -f compose.separado.yaml run --rm --no-deps --entrypoint caddy caddy validate --config /etc/dunker/caddy/Caddyfile --adapter caddyfile
}
# Run validation in an explicit fail-fast subshell; Bash functions in an if
# condition otherwise suppress errexit even for failures inside the function.
set +e
( set -e; validate )
validation_status=$?
set -e
if [[ $validation_status -ne 0 ]]; then manager rollback;echo 'Validação falhou; arquivos restaurados antes da ativação. Confira o relatório.' >&2;exit 1;fi
docker compose -f compose.separado.yaml up -d --no-build
docker compose -f compose.separado.yaml restart
if ! docker compose -f compose.separado.yaml exec -T admin python3 /opt/dunker/sharepoint_activate.py;then echo 'Ativação do plugin pendente; ative Dunker · Integrações no menu de plugins do Grafana.' >&2;fi
docker compose -f compose.separado.yaml ps
python3 "$package/scripts/docker_audit.py" --project "$project" --output "$report" --stage depois
manager inspect --output "/projeto/$report_relative" --stage depois
echo "Projeto completo atualizado. Revisão antes/depois: $report"
echo 'Use apenas compose.separado.yaml. Credenciais novas estão em config/secrets; guarde no seu cofre.'
