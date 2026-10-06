# Validação do pacote completo 1.4.3

Preparado em 05/10/2026. Nesta revisão, os 21 testes SharePoint e os 8 testes do instalador passaram (29 testes Python). A base 1.4.1 havia passado por 55 testes Python: 53 aprovados e 2 ignorados por dependências ICMP/SNMP indisponíveis. Três testes Node aprovados: conversão GB/TB e comportamento da tela SharePoint, registro do plugin e montagem das páginas nativas com representações simplificadas do DOM. Isso não é uma validação visual no navegador.

```bash
python3 -m unittest discover -s tests -v
node tests/test_plugin.js
node tests/test_native_ui.js
node tests/test_sharepoint_ui.js
```

## Revisão SharePoint 1.4.3

- Linhas repetidas consolidadas por ID e URL, sem dupla contagem; mesmo ID com URLs distintas distinguido em ordem estável; valores conflitantes mantêm uma linha completa e geram aviso.
- Testes de duplicação verificam total em bytes nas métricas, aviso persistente no snapshot, IDs/seleções válidos, estabilidade com CSV invertido e recusa de datas ou números inválidos em cópias.
- Não houve acesso ao CSV real do cliente: a causa da repetição e o total final devem ser conferidos no SharePoint após instalar.

- Corrigida a rejeição do domínio regional `reportsncu.office.com` e do caminho exato `/data/v1.0/download`, preservando a query assinada. Teste confirma CSV, chamada de download sem Bearer e recusa de URLs parecidas ou caminhos incorretos.

- CSV baixado por URL temporária, sem Authorization; cada redirecionamento validado; cabeçalhos Location sem distinção de maiúsculas/minúsculas.
- Domínios parecidos, URLs malformadas, HTTP, credenciais, porta incorreta, caminho fora de download, destinos privados e loops recusados. Diagnósticos sem URL assinada ou segredo.
- Transporte HTTP local confirma que não há redirecionamento automático do Bearer.
- GB/TB fracionários normalizados em GiB, unidade preservada, integrações antigas sem migração destrutiva e métricas em bytes inalteradas.
- UI exercitada com DOM simplificado: passo a passo aberto acima dos campos, troca de unidade com conversão, payload de salvamento e reabertura de integrações antigas/em TB.
- A tentativa de teste visual não pôde iniciar: Playwright existe, mas o navegador Chromium não está instalado. Não houve inspeção visual nem sessão Grafana real.

## Cobertura

- Sessão Grafana verificada por HTTP: Viewer, Editor e Admin; organização; sessão inválida; falha do Grafana; cabeçalhos de identidade falsificados; bloqueio de autenticação Basic antiga.
- Troca de papel e revogação de política em sessões já conectadas; padrão automático de usuários e atribuição individual por integração; Admin mantém gestão.
- Origin obrigatório nas alterações; bloqueio de requisições de outra origem; política inválida bloqueia acesso e não sobrescreve a política anterior.
- Renovação do cookie de sessão pelo Grafana retransmitida ao navegador; cookies não entram no JSON público.
- API de links não altera/exclui dispositivos SNMP por ID; campos de monitor que tentam mudar a classificação são recusados.
- Endereços antigos redirecionam para as páginas nativas. Páginas de links e SNMP carregam somente sua própria lista; modos de consulta e edição exercitados no teste Node.
- Preservação de inventários, política de permissões, credenciais, dados privados, volumes, configuração Caddy, fontes e regras personalizadas nas atualizações. Serviço admin sem porta publicada; volume privado de permissões adicionado.
- Regressão de CRUD e testes de links, SNMP, SharePoint, coleta assíncrona, credenciais, relatórios e exportação; integridade, backup e rollback do instalador.

## Limites

Docker, PowerShell, navegador local, Grafana e o binário SNMP exporter não estão disponíveis neste ambiente. ICMP real está bloqueado. Não houve aplicação no SRV-DUNKER, coleta Microsoft 365 real nem consulta ao SonicWall real. Dois testes dependentes de ICMP/SNMP real foram ignorados.

A autenticação foi testada contra uma simulação HTTP da API Grafana, sem banco real de sessões. A aparência, navegação e compatibilidade do plugin precisam da conferência no Grafana instalado. O instalador valida Compose, Prometheus principal, Prometheus SharePoint e Caddy no servidor antes de ativar. Siga `docs/PERMISSOES-GRAFANA.md` para conferir os perfis após a instalação.

## Referências de implementação

- Grafana: [papéis e permissões](https://grafana.com/docs/grafana/latest/administration/roles-and-permissions/).
- Grafana: [autenticação de app plugins](https://grafana.com/developers/plugin-tools/how-to-guides/app-plugins/add-authentication-for-app-plugins).

O controle por integração é implementado no backend Dunker; não depende de RBAC personalizado da edição Enterprise.
