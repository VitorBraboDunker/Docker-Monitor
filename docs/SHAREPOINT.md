# Dunker Monitor — SharePoint

Componente integrado ao Dunker Monitor completo 1.4.3. Instalação, atualização e revisão usam o instalador único descrito no README principal.

## O que foi entregue

- **Configuração dentro do Grafana:** plugin local `Dunker · Integrações`, com página SharePoint em `/a/dunker-integracoes-app/sharepoint`. A interface é renderizada na página do Grafana, sem iframe. A API verifica a sessão Grafana e o perfil de acesso a SharePoint; o token do coletor fica somente no servidor.
- **Permissões:** Viewer consulta, Editor edita e Admin gerencia por padrão. Ajuste o acesso por usuário na guia Permissões; veja `PERMISSOES-GRAFANA.md`. As URLs antigas redirecionam para o plugin.
- Cadastro e edição por cliente; teste e descoberta de sites; seleção automática de todos os sites ou lista específica; apelidos para sites com nomes ocultos; pausa, exclusão e coleta manual.
- Coleta automática de relatórios de uso pelo Microsoft Graph, sem agente no cliente.
- Capacidade total cadastrada manualmente, intervalos e limites de alerta editáveis pela tela. Expiração do segredo pode ser informada para gerar alerta antecipado.
- Dois dashboards provisionados: **Dunker · SharePoint · Clientes** e **Dunker · SharePoint · Detalhes**. A visão geral contém quadrados por cliente, clicáveis para detalhes.
- Histórico diário por data do relatório em SQLite e exportação CSV pela tela. Métricas em Prometheus dedicado com retenção de até 365 dias, também limitada a 2 GB.
- Alertas de uso em atenção/crítico/emergência, coleta ausente/antiga/com erro, capacidade não informada, segredo próximo da expiração e coletor indisponível. Eles seguem para o Alertmanager já existente; notificações dependem dos destinatários/canais que estiverem configurados nele.

A integração guarda **o histórico do uso de armazenamento**. Ela não faz backup dos arquivos do SharePoint nem modifica os limites de armazenamento na Microsoft.

## Instalação

Este componente já está incluído no pacote completo 1.4.3. Use `ATUALIZAR-PROJETO.ps1` no Windows ou `atualizar-projeto.sh` no Ubuntu, conforme o README principal. Não há complemento anterior obrigatório. Todos os serviços usam somente `compose.separado.yaml`.

## Acessar e cadastrar o primeiro cliente

Abra o **mesmo endereço e porta que você já usa para o Grafana**, acrescentando:

```text
/a/dunker-integracoes-app/sharepoint
```

Exemplo, somente se sua porta atual continuar sendo 8443:

```text
http://172.16.27.51:8443/a/dunker-integracoes-app/sharepoint
```

Acesso alternativo:

```text
http://172.16.27.51:8443/a/dunker-integracoes-app/sharepoint
```

Para cadastrar a credencial, use acesso administrativo protegido por HTTPS ou por rede/VPN restrita, conforme seu ambiente. Este pacote mantém o endereço e o modo de acesso que você configurou no projeto.

1. No Microsoft Entra do cliente, abra **Registros de aplicativos → Novo registro**. Nome sugerido: `Dunker Monitor — SharePoint`. Use uma aplicação de tenant único para começar. O fluxo desta integração não precisa de URI de redirecionamento.
2. Copie **ID do diretório (tenant)** e **ID do aplicativo (cliente)**.
3. Abra **Permissões de API → Adicionar uma permissão → Microsoft Graph → Permissões de aplicativo**.
4. Adicione **Reports.Read.All** e conceda o consentimento administrativo para a organização. Essa permissão permite ler relatórios de uso de Microsoft 365; não é uma permissão restrita somente ao relatório SharePoint. A aplicação usa apenas o endpoint SharePoint implementado.
   **Sites.Read.All** (Aplicativo) permite consultas diretas de sites por `/sites/...`; pode permanecer se já foi concedida, mas o coletor atual descobre sites pelo CSV de uso e não chama esse endpoint. Portanto, ela não é obrigatória para este fluxo. **Sites.Selected** não substitui **Reports.Read.All**. Use permissões de aplicativo, não delegadas.
5. Em **Certificados e segredos**, crie um segredo e guarde seu valor no cofre de credenciais. Copie o **valor do segredo**, não o ID. Não use a senha de um administrador no coletor.
6. Na nossa tela, clique **Integrar cliente** e informe cliente, nome, IDs e valor do segredo. A autenticação desta versão é por segredo de aplicativo; autenticação por certificado não foi incluída.
7. Em **Capacidade total do cliente**, informe o valor e selecione **GB ou TB** para o total exibido no centro de administração SharePoint → Sites ativos. A Microsoft calcula esse espaço em unidades binárias; 1 GB nesta tela = 1 GiB = 1.073.741.824 bytes; 1 TB = 1.024 GB. Ao trocar a unidade, a tela converte o valor sem mudar a capacidade real. A unidade escolhida é preservada; integrações antigas mantêm o valor existente em GB. Deixe 0 se ainda não souber: o painel indicará capacidade não informada e não calculará ocupação percentual.
   O token OAuth e os IDs dos sites são obtidos automaticamente. O coletor de relatórios não exige hostname/caminho manual. Em uma consulta direta de site pelo Graph, hostname tem o formato `cliente.sharepoint.com` e caminho `/sites/NomeDoSite` ou `/` para a raiz; isso não substitui as credenciais Entra.
8. Clique **Testar conexão e descobrir sites**. O teste consulta dados reais, mas não grava um snapshot histórico nem salva o formulário.
9. Selecione todos os sites ou os desejados. No modo todos, sites novos entram automaticamente nas próximas coletas. No modo selecionados, marque pelo menos um site. É possível dar apelidos aos sites.
10. Salve e clique **Coletar agora** na lista. O coletor também executa conforme o intervalo configurado.
11. Abra o dashboard pelo botão da tela. Aguarde até 5 minutos para o scrape das primeiras métricas.

Nomes e URLs de sites podem vir ocultos pela configuração de privacidade dos relatórios Microsoft 365. Nesse caso, a integração mantém a identificação devolvida e permite apelidos. Um administrador global pode avaliar **Centro de administração Microsoft 365 → Configurações → Configurações da organização → Serviços → Relatórios → desmarcar ocultar nomes de usuários, grupos e sites → Salvar**. A opção afeta todos os relatórios da organização; a aplicação não muda essa opção automaticamente. BYOK/Customer Lockbox também podem afetar a exposição de URLs.

## Download do relatório e diagnóstico — 1.4.3

O fluxo é OAuth em `login.microsoftonline.com` → Graph com Bearer → HTTP 302 com `Location` → download do CSV em HTTPS, **sem Authorization**. O download aceita os hosts exatos `reports.office.com`, `reports.office365.com` e `reportsncu.office.com`, porta 443 e caminhos `/data/download/...` ou `/data/v1.0/download` (com a query assinada preservada). Valida cada salto de uma cadeia limitada de redirecionamentos; não aceita domínios parecidos, subdomínios arbitrários, HTTP nem credenciais na URL. O servidor precisa de saída HTTPS/DNS para os endpoints Microsoft.

O domínio observado no retorno do Graph deste cliente foi `reportsncu.office.com`. As versões 1.4.0/1.4.1 não o incluíam na lista de destinos. A versão 1.4.3 corrige essa omissão e também reconhece o formato `/data/v1.0/download?token=...`, além do formato `/data/download/...`. Apenas os hosts exatos acima são aceitos; não foi liberado `*.office.com`.

A URL pré-autenticada é usada inteira, incluindo a query, sem o Bearer do Graph. O teste de regressão simula o retorno regional, verifica a chamada exata de download e confirma a rejeição de domínios parecidos e caminhos fora dos formatos permitidos. A coleta real deve ser confirmada no cliente. Se outra falha de destino ocorrer, informe somente o domínio exibido, sem URL temporária assinada, token ou segredo.

Para atualizar no SRV-DUNKER, extraia o pacote em uma pasta separada, abra PowerShell na pasta extraída e execute:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ATUALIZAR-PROJETO.ps1 -Projeto "C:\Users\VitorBrabodaSilvaDun\Docker\dunker-monitor"
```

Depois recarregue a página do Grafana (Ctrl+F5), abra a integração salva e clique **Testar conexão e descobrir sites**. Após confirmar os sites, salve e use **Coletar agora**. A instalação preserva a base privada e as credenciais existentes; não é preciso recriar o aplicativo Entra para corrigir o download.

## Linhas e IDs repetidos — 1.4.3

A versão anterior interrompia a leitura ao encontrar um ID de site repetido. O erro observado confirma que há repetição no CSV recebido, mas não determina se as linhas são idênticas ou possuem URLs/valores diferentes. A versão 1.4.3 trata esses casos explicitamente:

- Mesmo ID e mesma URL: consolida em um registro; o uso não é somado novamente. URLs visíveis são comparadas sem distinção de maiúsculas/minúsculas ou barra final.
- Mesmo ID e URLs diferentes: distingue os registros pela URL e mantém IDs internos determinísticos, independentemente da ordem das linhas. A primeira URL em ordem estável conserva o ID original; as demais recebem IDs derivados do ID e URL. Identificadores opacos de URL ajudam na distinção, mas não são expostos como URLs visíveis. Confira a seleção de sites se esse caso surgir após uma coleta anterior.
- Mesmo ID/URL, mesma data e valores diferentes: mantém uma linha completa com o maior uso (desempate por limite e quantidade de arquivos), sem somar cópias. É uma regra conservadora do Dunker, não uma garantia de qual linha é a correta na Microsoft.
- Linhas inválidas continuam recusadas, mesmo se houver outra cópia válida. Sites excluídos continuam ignorados; datas de relatório inconsistentes continuam recusadas.

A tela informa quantas linhas foram consolidadas. Se houver valores divergentes ou IDs compartilhados por URLs diferentes, mostra um aviso no teste, na coleta manual e no cartão da integração salva. Nesses casos, confira a lista e o total no centro de administração SharePoint: sem o CSV real não é possível concluir a causa da duplicação ou garantir que URLs diferentes representem sites distintos em vez de uma renomeação.

As métricas e o histórico usam os registros consolidados. O aviso acompanha o snapshot, sem alterar o formato dos campos canônicos de capacidade. A atualização mantém o banco, as credenciais, a capacidade GB/TB e as configurações do Grafana.

## Regras e valores iniciais

| Campo | Padrão |
|---|---|
| Intervalo de consulta à Microsoft | 24 horas, editável de 6 a 168 horas |
| Atenção | 80% |
| Crítico | 90% |
| Emergência | 95% |
| Relatório/coleta considerados antigos | 96 horas, editável |
| Capacidade total | Manual; 0 = desconhecida |
| Seleção de sites | Todos |
| Snapshots SQLite | Até 365 dias |
| Histórico Prometheus dedicado | Até 365 dias ou 2 GB, o limite atingido primeiro |

A idade do relatório e a idade da última coleta são verificadas separadamente. Não basta conseguir consultar a API se ela continua retornando um relatório antigo. Uma falha mantém o último consumo conhecido e marca a situação como dados indisponíveis. Os painéis mostram tanto a data do relatório como o horário da última coleta bem-sucedida.

## Como interpretar os dados

- O **uso geral** é a soma do consumo dos sites ativos presentes no relatório Microsoft. A lista selecionada controla apenas o detalhamento por site; não reduz artificialmente o consumo geral do cliente.
- A capacidade total não é obtida automaticamente nesta versão. Revise o valor informado quando licenças ou armazenamento adicional mudarem.
- **Limite do site não é capacidade do tenant.** No modo automático, vários sites podem ter limite de 25 TB, embora o cliente tenha um pool total menor. A aplicação nunca soma essas cotas para calcular a capacidade total.
- O relatório pode diferir do centro de administração por regras de inclusão e atraso. A Microsoft informa que dados de uso de armazenamento podem não refletir mudanças das últimas 24–48 horas. A frequência de consulta não transforma o relatório em dados de tempo real.
- A consulta `period='D7'` retorna o relatório de sites para aquela janela de atividade. Ela **não fornece sete snapshots históricos de consumo por site**. Nosso histórico começa com as coletas da instalação, em vez de inventar valores anteriores.
- Crescimentos em 7 e 30 dias exigem snapshots nas datas correspondentes do relatório. Se não houver histórico suficiente, o campo fica sem valor. Os mesmos dados republicados no mesmo dia atualizam o snapshot, sem duplicar dias.
- A projeção usa o crescimento líquido dos últimos 7 dias. Ela aparece quando há crescimento positivo e capacidade conhecida; 0 indica que o consumo já alcançou a capacidade. É uma estimativa, sem garantia de data de esgotamento.
- Os gráficos Prometheus mostram o valor conhecido no horário de coleta. A data de origem é exibida separadamente no dashboard.
- Ao pausar ou excluir, a integração deixa de emitir métricas novas. O histórico permanece até a retenção. A exclusão remove a credencial da configuração ativa; backups anteriores do servidor podem continuar contendo a configuração anterior.

## Comandos para operação

Depois da instalação, use **somente `compose.separado.yaml`**:

```powershell
docker compose -f compose.separado.yaml up -d --no-build
docker compose -f compose.separado.yaml ps
docker compose -f compose.separado.yaml logs --tail 100 sharepoint sharepoint-prometheus admin grafana
```

O projeto recebe o atalho `INICIAR-COM-SHAREPOINT.ps1`, que você pode executar com a mesma opção Bypass usada acima. No Linux, use `bash iniciar-com-sharepoint.sh`.

As imagens publicadas continuam em 1.2.0 para o código Python. A integração nova é montada a partir dos arquivos do projeto, sem exigir build nem push no Docker Hub. O Prometheus adicional usa a versão do projeto atual. Não aplique este complemento ao `compose.unico.yaml`.

## Caso a configuração no Grafana não carregue

A ativação automática usa a conta `admin` e a senha do arquivo de credenciais do projeto. Se a senha real da conta foi alterada só pela interface do Grafana, a ativação pode ser recusada. Habilite manualmente Dunker · Integrações no menu de plugins do Grafana e recarregue a página.

Depois de alinhar a credencial de instalação com a conta administrativa, repita:

```powershell
docker compose -f compose.separado.yaml exec -T admin python3 /opt/dunker/sharepoint_activate.py
```

O script não imprime o segredo nem o token interno. Ele grava o token do coletor em `secureJsonData` no Grafana, que o criptografa. O token não é devolvido para o JavaScript da tela. Confira os logs do Grafana para rejeições do plugin local ou incompatibilidades da versão.

## Persistência, backup e arquivos

| Local | Conteúdo |
|---|---|
| `config/sharepoint/private/sharepoint.sqlite3` | Integrações, segredo de aplicativo e snapshots diários |
| `config/sharepoint/private/gateway_token` | Token interno entre backend admin e coletor |
| Volume Docker `sharepoint_prometheus_data` | Séries históricas para os dashboards |
| `config/sharepoint/prometheus.yml` / `rules.yml` | Scrape e alertas da integração |
| `config/grafana/plugins/dunker-integracoes-app` | Plugin instalável e módulo já pronto |
| `backups/completo-*` | Cópias dos arquivos alterados pelo instalador |

No Linux, o banco e o token são criados com modo 0600. O segredo de aplicativo fica no banco privado no servidor, **sem criptografia própria nesta versão**; proteja a pasta, os backups e o disco. No Windows, permissões dependem também das ACLs NTFS. A pasta privada é excluída do Git pelo instalador. Nunca inclua o banco ou o token em ZIPs enviados ao repositório.

Para uma cópia consistente do SQLite, pare apenas o coletor, copie a pasta privada para seu destino protegido e inicie novamente. Use o backup usual de volumes Docker para o volume Prometheus. A exportação CSV pela tela contém histórico de consumo, sem segredos; ela não substitui o backup da configuração.

O instalador é idempotente e mantém o token e os dados existentes ao reinstalar. Se a validação falhar, os arquivos são restaurados. Se a subida Docker falhar parcialmente, os arquivos aplicados são mantidos para recuperação consistente; use os logs e as instruções do README principal. A restauração não apaga os dados privados nem os volumes.

## Validação

Consulte `VALIDACAO.md` nesta pasta para os testes do pacote completo e seus limites. O instalador executa a validação real de Compose, Prometheus e Caddy no servidor antes da ativação.

## Referências oficiais utilizadas

- Microsoft Graph, relatório por site: https://learn.microsoft.com/en-us/graph/api/reportroot-getsharepointsiteusagedetail?view=graph-rest-1.0
- Microsoft Entra, client credentials: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow
- SharePoint, capacidade e limites: https://learn.microsoft.com/en-us/sharepoint/manage-site-collection-storage-limits
- Relatórios e nomes ocultos: https://learn.microsoft.com/en-us/microsoft-365/admin/activity-reports/sharepoint-site-usage-ww?view=o365-worldwide
- Grafana, autenticação e proxy de aplicativos: https://grafana.com/developers/plugin-tools/how-to-guides/app-plugins/add-authentication-for-app-plugins
- Grafana, metadados do plugin: https://grafana.com/developers/plugin-tools/reference/plugin-json

Referências adicionais: [consulta direta de sites e Sites.Read.All](https://learn.microsoft.com/en-us/graph/api/site-get?view=graph-rest-1.0); [nomes ocultos nos relatórios](https://learn.microsoft.com/en-us/troubleshoot/microsoft-365/admin/miscellaneous/reports-show-anonymous-user-name).
