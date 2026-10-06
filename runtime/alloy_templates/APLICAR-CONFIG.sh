#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then echo 'Execute como root: sudo bash APLICAR-CONFIG.sh' >&2; exit 1; fi
agent_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if ! command -v alloy >/dev/null; then
 echo 'Instale primeiro o Grafana Alloy conforme https://grafana.com/docs/alloy/latest/set-up/install/linux/' >&2
 exit 1
fi
if [[ ${1:-} != '--substituir-configuracao' && -f /etc/alloy/config.alloy ]]; then
 echo 'Alloy ja possui configuracao. Para substitui-la com backup: sudo bash APLICAR-CONFIG.sh --substituir-configuracao' >&2
 exit 1
fi
IFS= read -r -s -p 'Senha de ingestao (system.ingest_password da central): ' DNK_INGEST_PASSWORD
printf '\n'
[[ -n $DNK_INGEST_PASSWORD ]] || { echo 'Senha vazia.' >&2; exit 1; }
export DNK_INGEST_PASSWORD
alloy validate "$agent_dir/config.alloy"
agent_backup=$(mktemp -d /var/backups/dunker-alloy-XXXXXXXX)
chmod 700 "$agent_backup"
agent_was_running=false
if systemctl is-active --quiet alloy; then agent_was_running=true; fi
agent_had_config=false; agent_had_env=false; agent_had_dropin=false
if [[ -f /etc/alloy/config.alloy ]]; then cp -a /etc/alloy/config.alloy "$agent_backup/config.alloy"; agent_had_config=true; fi
if [[ -f /etc/alloy/dunker.env ]]; then cp -a /etc/alloy/dunker.env "$agent_backup/dunker.env"; agent_had_env=true; fi
if [[ -f /etc/systemd/system/alloy.service.d/dunker.conf ]]; then cp -a /etc/systemd/system/alloy.service.d/dunker.conf "$agent_backup/dunker.conf"; agent_had_dropin=true; fi
agent_changed=false
restore_agent(){
 agent_exit=$?
 if [[ $agent_exit -ne 0 && $agent_changed == true ]]; then
  systemctl stop alloy || true
  if $agent_had_config; then cp -a "$agent_backup/config.alloy" /etc/alloy/config.alloy; else rm -f /etc/alloy/config.alloy; fi
  if $agent_had_env; then cp -a "$agent_backup/dunker.env" /etc/alloy/dunker.env; else rm -f /etc/alloy/dunker.env; fi
  if $agent_had_dropin; then cp -a "$agent_backup/dunker.conf" /etc/systemd/system/alloy.service.d/dunker.conf; else rm -f /etc/systemd/system/alloy.service.d/dunker.conf; fi
  systemctl daemon-reload
  if $agent_was_running; then systemctl start alloy || true; fi
 fi
 unset DNK_INGEST_PASSWORD
}
trap restore_agent EXIT
systemctl stop alloy
agent_changed=true
install -d -m 755 /etc/alloy /etc/systemd/system/alloy.service.d
install -m 644 "$agent_dir/config.alloy" /etc/alloy/config.alloy
# systemd EnvironmentFile quoting, including spaces, quotes, backslashes and dollars.
agent_escaped=${DNK_INGEST_PASSWORD//\\/\\\\}
agent_escaped=${agent_escaped//\"/\\\"}
umask 077
printf 'DNK_INGEST_PASSWORD="%s"\n' "$agent_escaped" > /etc/alloy/dunker.env
cat > /etc/systemd/system/alloy.service.d/dunker.conf <<'EOF'
[Service]
EnvironmentFile=/etc/alloy/dunker.env
EOF
if grep -q 'loki.source.journal' "$agent_dir/config.alloy"; then usermod -a -G systemd-journal alloy; fi
systemctl daemon-reload
systemctl enable alloy
systemctl restart alloy
systemctl is-active --quiet alloy
printf 'Configuracao aplicada. Backup: %s\nConfira as primeiras coletas no Grafana.\n' "$agent_backup"
