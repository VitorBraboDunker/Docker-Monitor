# Componentes e origem

As imagens oficiais preservam os avisos e licenças dos projetos de origem. Os binários e arquivos incorporados na variante única vêm das mesmas imagens. Os Dockerfiles fixam os digests usados; `images-lock.json` registra a origem de cada imagem.

| Componente | Versão | Origem |
|---|---|---|
| Grafana OSS | 13.2.2 | grafana/grafana |
| Prometheus | 3.13.3 LTS | prometheus/prometheus |
| Alertmanager | 0.34.1 | prometheus/alertmanager |
| Blackbox Exporter | 0.28.0 | prometheus/blackbox_exporter |
| SNMP Exporter | 0.30.1 | prometheus/snmp_exporter |
| Loki | 3.7.8 | grafana/loki |
| Alloy | 1.20.1 | grafana/alloy |
| Caddy | 2.11.4 | caddyserver/caddy |
| Python runtime | 3.13, imagem slim-bookworm | docker-library/python |
| Dunker Ping Exporter e supervisor | 1.0.0 | Código fonte incluído em runtime/ |

A configuração IF-MIB/MikroTik/HR é derivada do snmp.yml oficial do SNMP Exporter v0.30.1. O módulo SonicWall foi descrito a partir da SONICWALL-FIREWALL-IP-STATISTICS-MIB, com teste no dispositivo pendente.

A imagem única não executa Docker dentro do container. O supervisor inicia os nove processos e encerra o conjunto se algum deles terminar; a política Docker `unless-stopped` reinicia o conjunto. No modo separado, cada serviço tem sua própria política de reinício.
