#!/usr/bin/env bash
set -euo pipefail
[[ "$EUID" -eq 0 ]] || { echo 'Execute com sudo.';exit 1; }
. /etc/os-release
[[ "$ID" == ubuntu ]] || { echo 'Instalador para Ubuntu.';exit 1; }
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1;then echo 'Docker e Compose já instalados.';exit 0;fi
for package in docker.io docker-compose docker-compose-v2 podman-docker;do
 if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed';then echo "Pacote existente: $package. Consulte o guia oficial antes de substituir.";exit 1;fi
done
apt-get update
apt-get install -y ca-certificates curl python3 unzip
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version
