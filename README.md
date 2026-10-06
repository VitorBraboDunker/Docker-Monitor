# Dunker Monitor — primeira versão oficial 1.0.0

Base de migração: pacote Beta 1.4.3. A numeração 1.0.0 identifica o lançamento oficial, não uma volta para os arquivos antigos.

## Atualizar no SRV-DUNKER

Extraia este ZIP em uma pasta diferente da instalação. Abra PowerShell nessa pasta e execute:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ATUALIZAR-PROJETO.ps1 -Projeto "C:\Users\VitorBrabodaSilvaDun\Docker\dunker-monitor"
```

O instalador revisa os arquivos e containers, cria backup, migra as credenciais, valida Compose/Prometheus/Caddy, remove os containers obsoletos e reinicia os serviços. Use somente `compose.separado.yaml` após a atualização. Não apaga volumes Docker. Monitores existentes precisam ter CLIENTE e UNIDADE; cadastros antigos Cliente/Unidade são convertidos automaticamente.

Para Ubuntu/Azure:

```bash
bash atualizar-projeto.sh /opt/dunker-monitor
```

Instalação nova: acrescente `-NovaInstalacao` no PowerShell ou `--nova-instalacao` no Bash. Uma instalação nova começa sem clientes de demonstração e inclui o próprio servidor central.

## O que mudou

- 10 dashboards oficiais: individual e consolidado por cliente para Links, Firewalls/Roteadores, Servidores e SharePoint; conformidade global; domínios/certificados.
- CLIENTE e UNIDADE obrigatórios; ID estável para cada ativo. Painéis do cliente abrem o detalhamento do equipamento.
- Contrato único de status: OK, Sem Dados, Atenção, Grave, Crítico e Pausado.
- Qualquer anomalia em ativo habilitado marca o cliente Fora de Conformidade. Um cliente com todos os ativos pausados aparece Pausado. Excluídos ficam fora dos dashboards operacionais.
- Exclusão recuperável, preservando ID, parâmetros, credencial e histórico; reativação e downloads na central.
- Gerador de Alloy Windows/Linux com seleção de CPU, memória, disco, rede, serviços e logs.
- Correções de contraste em formulários, seleções de perfis e tabelas das interfaces SNMP.
- Remoção das regras/dashboards Dunker legados, do Blackbox redundante e do Prometheus dedicado ao SharePoint. O coletor multiprotocolo monitora ICMP/HTTP/TCP/DNS. O Prometheus principal recebe também o SharePoint.

## Acessar dentro do Grafana

Abra **Dunker · Integrações** no menu do Grafana. Páginas: Links, Firewalls/SNMP, SharePoint, Servidores e histórico, Criar Alloy, Itens Excluídos, Domínios/certificados e Permissões.

Viewer/Editor recebem perfis automaticamente; Admin gerencia permissões e configurações globais. A política agora inclui Servidores/Alloy. Perfis anteriores recebem inicialmente o mesmo nível de acesso de Links para essa área; ajuste em Permissões. As ações são verificadas no servidor a cada requisição.

## Arquivos centrais

| Arquivo | Conteúdo |
| --- | --- |
| `config/global/credentials.json` | Credenciais do ambiente, autenticação de ingestão, SNMP e segredos Microsoft; criado pela migração. |
| `config/global/domains.json` | Endereço público, portas, modo TLS, certificados e destinos das consultas online. |
| `config/global/status.json` | Limites de utilização e durações de incidentes/recuperação. |
| `config/targets/inventory.json` | Inventário de links, equipamentos e servidores, inclusive registros recuperáveis. |
| `config/excluidos/` | Catálogos gerados exclusivamente para itens excluídos. |
| `config/history/monitor-history.sqlite3` | Telemetria agregada por ativo e histórico de ações/status. |
| `config/sharepoint/private/sharepoint.sqlite3` | Cadastros e snapshots de uso do SharePoint. |

As credenciais existentes são preservadas. Em instalações novas, senhas são geradas individualmente; não há uma senha fixa compartilhada. A fonte de configuração é o arquivo global. Grafana e SNMP exigem arquivos próprios: eles são **adaptadores gerados**, não arquivos de configuração para editar. Contas e hashes de senha dos usuários continuam no banco nativo do Grafana.

Depois de editar os arquivos globais, renderize os adaptadores e recrie os serviços:

```powershell
docker run --rm --entrypoint python3 --mount "type=bind,source=C:\Users\VitorBrabodaSilvaDun\Docker\dunker-monitor,target=/projeto" vitorbrabodunker/dunker-monitor-separado:1.2.0 /projeto/scripts/global_settings.py --project /projeto
docker compose -f compose.separado.yaml up -d --force-recreate
```

Linux: `python3 scripts/global_settings.py --project /opt/dunker-monitor` e depois `docker compose -f compose.separado.yaml up -d --force-recreate`.

Alterar `grafana_admin_password` não redefine sozinho uma conta já existente no banco do Grafana. Altere a senha no Grafana e mantenha o valor global correspondente. Alterações de ingestão precisam de um novo hash Caddy; veja `docs/CONFIGURACAO-GLOBAL.md`.

## Alloy

Na página Criar Alloy, informe CLIENTE, UNIDADE, hostname e sistema operacional. Selecione os itens, gere e baixe `config.alloy`. O servidor fica cadastrado como Sem Dados até começar a enviar métricas. A página gera configuração; a instalação do serviço no servidor de destino continua necessária.

Configure `DNK_INGEST_PASSWORD` **no ambiente do serviço Alloy** com `system.ingest_password` do arquivo global. A configuração não inclui senhas. Valide com `alloy validate config.alloy` antes de substituir o arquivo e reiniciar o serviço. Agents antigos podem alimentar os indicadores por cliente/unidade/hostname; novos arquivos usam as tags obrigatórias em maiúsculas.

## Histórico e limites de validação

Prometheus: 30 dias de séries técnicas. Histórico agregado exportável: 365 dias a partir da v1.0. Ações e transições de status são preservadas. SharePoint mantém snapshots diários por 365 dias e permite exportação CSV, inclusive de integrações excluídas. A v1.0 não recria medições passadas que nunca foram coletadas.

A capacidade total do tenant SharePoint permanece manual nesta base. A API usada devolve limites de sites; eles não são somados para estimar a capacidade total da organização. CPU/RAM SNMP dependem do firmware/MIB e podem não ser expostas.

Testes locais cobrem código, APIs, status, migração, restauração, isolamento de segredos e montagens da interface. Docker, binários promtool/Caddy/Alloy e validação visual no Grafana real não estão disponíveis no ambiente de preparação. O instalador exige a validação do Compose, das regras Prometheus e do Caddy antes da ativação. Valide também os agentes Alloy nos sistemas de destino.

A imagem `dunker-monitor-separado:1.2.0` permanece como base Python já publicada; os arquivos v1.0 do runtime são montados do projeto. Nenhuma imagem com uma tag inexistente é exigida.
