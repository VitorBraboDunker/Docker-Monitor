# Dunker Monitor

Versão revisada em 30/09/2026. Grafana, Prometheus, Blackbox, ping multipacote, SNMP, Loki, Alloy e Alertmanager, com Caddy como entrada central por HTTP.

Leia **docs/REVISAO-2026-09-30.md** para atualização no Windows, cadastro de pings, acesso por IP, configuração central, achados e limitações de validação.

```powershell
docker compose -f compose.separado.yaml up -d --build
```

Grafana: `http://IP_DO_SERVIDOR:8443/`.
Cadastro visual: `http://IP_DO_SERVIDOR:8443/monitoramento/`.

A porta e interface de entrada ficam em `.env`; as rotas ficam em `config/caddy/Caddyfile`. O ZIP de atualização preserva senhas, inventário e `.env` existentes. Não apague volumes Docker. O pacote completo é uma cópia da configuração enviada com as mudanças aplicadas e inclui os arquivos de senha originais: mantenha-o privado.
