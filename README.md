# Dunker Monitor completo — 1.4.3

Esta revisão corrige o tratamento de linhas com IDs de site repetidos, sem duplicar o armazenamento, e mantém a correção do download regional em reportsncu.office.com/data/v1.0/download, melhora o download protegido do relatório SharePoint, adiciona diagnóstico do domínio de redirecionamento e capacidade em GB/TB, e coloca o passo a passo Microsoft 365 acima dos campos. Veja `docs/SHAREPOINT.md`.

Um ZIP com a base, a central de cadastro, integrações SNMP, dashboards de clientes/links e coleta de armazenamento SharePoint. O instalador revisa o Docker e os arquivos existentes, acrescenta componentes ausentes e consolida a operação em **somente `compose.separado.yaml`**. Não precisa instalar os ZIPs antigos primeiro.

Esta entrega usa containers separados. A integração SharePoint guarda histórico do uso de armazenamento; não é backup dos documentos Microsoft 365.

## Atualizar no Windows / SRV-DUNKER

1. Deixe o Docker Desktop em execução, no modo de containers Linux.
2. Extraia este ZIP em uma pasta separada, por exemplo Downloads. Não copie seus arquivos por cima do projeto manualmente.
3. Abra o PowerShell na pasta extraída que contém `ATUALIZAR-PROJETO.ps1`.
4. Execute usando a pasta **real da instalação**:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ATUALIZAR-PROJETO.ps1 -Projeto "C:\Dunker\dunker-monitor"
```

Se sua instalação estiver na pasta anterior, use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ATUALIZAR-PROJETO.ps1 -Projeto "C:\Users\VitorBrabodaSilvaDun\Docker\dunker-monitor"
```

O script compara esse caminho com as etiquetas dos containers. Se os containers ativos indicarem outra pasta, ele informa o caminho encontrado e interrompe a aplicação antes de alterar o projeto. Não é necessário Python no Windows: a preparação roda na imagem Docker já usada pela base.

Depois da atualização, os scripts de iniciar/parar ficam também na pasta do projeto. Todos os comandos passam a usar somente `compose.separado.yaml`; não acrescente os arquivos de integrações antigos ao comando. Eles podem permanecer na pasta como referência, mas suas configurações foram incorporadas.

## Revisar sem atualizar

Na pasta do ZIP extraído:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\VERIFICAR-PROJETO.ps1 -Projeto "C:\Dunker\dunker-monitor"
```

Isso consulta Docker e arquivos e grava relatórios; não altera configurações nem reinicia serviços. Pode baixar a imagem auxiliar caso ela ainda não esteja disponível.

## Instalação nova

Use esta opção **somente em uma pasta nova**, sem o projeto já instalado:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ATUALIZAR-PROJETO.ps1 -Projeto "C:\Dunker\dunker-monitor" -NovaInstalacao
```

O instalador cria credenciais aleatórias no próprio servidor. Não há senhas de outra instalação no ZIP. O padrão é SRV-DUNKER, `http://172.16.27.51:8443`. Para uma instalação nova com outro endereço/porta, crie a pasta de destino e copie `.env.example` para `.env` nessa pasta, ajustando os valores antes do comando; o instalador preserva esse arquivo.

A senha inicial está em `config/secrets/grafana_admin_password`. Ela não é exibida na saída nem nos relatórios. Guarde as novas credenciais no seu cofre. Restringa o acesso de usuários locais à pasta do projeto e aos backups; o arquivo de senha e chave do Grafana precisa ser legível pelo usuário do container.

## Ubuntu / Azure

Com Docker Engine, Compose v2 e Python 3 disponíveis, extraia o ZIP em outra pasta e execute:

```bash
sudo bash atualizar-projeto.sh /opt/dunker-monitor
# Apenas revisar:
sudo bash atualizar-projeto.sh /opt/dunker-monitor --somente-verificar
# Instalação nova, somente se essa pasta ainda não tiver o projeto:
sudo bash atualizar-projeto.sh /opt/dunker-monitor --nova-instalacao
```

Os coletores e o instalador usam Python da imagem do projeto; a revisão do Docker no Ubuntu usa Python 3 do host. O pacote inclui a biblioteca YAML necessária ao instalador, sem instalação de dependências pelo pip. A instalação precisa acessar o registro Docker para imagens que ainda não estejam em cache.

## O que é revisado e preservado

O instalador grava `diagnostico/revisao-DATA-HORA/` no projeto, com:

- `docker-antes.json/.txt` e `docker-depois.json/.txt`: imagens, estado, saúde disponível, nome do projeto Compose, caminho real, portas e volumes/montagens.
- `arquivos-antes.json/.txt` e `arquivos-depois.json/.txt`: arquivos ausentes/diferentes, serviços definidos, presença dos arquivos de credenciais e contagens do inventário.

Os relatórios não incluem senhas, tokens, variáveis de ambiente dos containers nem conteúdo dos cadastros. `managed` significa arquivo mantido pelo pacote; `seed` significa que é criado apenas se estiver ausente.

São preservados `.env`, inventário e targets existentes, credenciais SNMP, chave estável do Grafana, dados privados SharePoint, portas existentes, nomes de volumes e identidade do projeto Compose detectada no Docker. Também são preservadas notificações do Alertmanager, configuração existente do Alloy, fontes de dados existentes e grupos/regras/jobs personalizados reconhecidos. Arquivos de código, dashboards provisionados do projeto e suas regras são atualizados para esta versão; personalizações nesses arquivos ficam no backup.

O instalador faz backup dos arquivos que vai modificar em `backups/completo-DATA-HORA/`. Valida Compose, Prometheus principal, Prometheus SharePoint e Caddy antes da ativação. Se a validação falhar, restaura os arquivos alterados. Esse backup de atualização não copia os volumes de histórico Docker: volumes existentes são mantidos e nunca removidos pelo instalador.

Depois da validação, os serviços são iniciados/recriados e reiniciados para carregar o código e o plugin. Haverá uma breve interrupção do monitoramento. Se a inicialização Docker falhar parcialmente, os arquivos novos ficam aplicados para recuperação consistente; consulte os logs e o backup. Complementos Compose desconhecidos, modo de container único e padrões de regras personalizados que possam causar duplicação precisam de revisão específica e fazem o instalador interromper antes da aplicação.

## Configuração e dashboards

No endereço que você já usa para o Grafana:

| Recurso | Caminho |
|---|---|
| Links / Ping / HTTP / TCP / DNS | `/a/dunker-integracoes-app/links` |
| Firewalls e roteadores SNMP | `/a/dunker-integracoes-app/snmp` |
| SharePoint | `/a/dunker-integracoes-app/sharepoint` |
| Perfis e permissões (Admin) | `/a/dunker-integracoes-app/permissoes` |
| Dashboards provisionados | Menu Dashboards → pasta Dunker |

O pacote contém 11 dashboards: geral, links, máquinas, firewall/SNMP, Loki, clientes de links, visão geral de links, equipamentos, detalhes do equipamento e duas visões SharePoint. Os dashboards existentes salvos no banco do Grafana permanecem no volume.

Para SharePoint, cadastre tenant ID, application ID, segredo da aplicação, cliente, capacidade total em GiB, intervalo e limites pela tela. O registro da aplicação, permissão `Reports.Read.All` e consentimento administrativo são feitos no Microsoft Entra. A capacidade total é informada manualmente; os relatórios Microsoft podem atrasar 24–48 horas. Os segredos Microsoft ficam no SQLite privado do coletor, com permissões restritas; não são criptografados em repouso pelo aplicativo. Veja `docs/SHAREPOINT.md` para configurar o primeiro cliente.

A página usa um plugin local do projeto. O Compose permite explicitamente o ID `dunker-integracoes-app` sem assinatura. O instalador tenta ativá-lo automaticamente; se a senha admin do Grafana foi alterada na interface e não corresponde ao arquivo, a ativação pode precisar ser feita depois. Os endereços antigos redirecionam para o plugin; o acesso usa a sessão do Grafana. Para ativar manualmente, abra Administração → Plugins e dados → Plugins → Dunker · Integrações e habilite o app. Nenhum novo coletor ou Prometheus SharePoint publica porta na rede.

Para SonicWall, MikroTik ou SNMP genérico, veja `docs/INTEGRACOES-SNMP.md`. As telas de edição/discovery usam o backend atualizado incluído neste pacote.

## Perfis de usuário

O papel escolhido no Grafana aplica automaticamente um perfil de configuração:

| Papel Grafana | Perfil inicial | Permissão inicial |
|---|---|---|
| Viewer | Consulta | Consultar links, SNMP e SharePoint |
| Editor | Operador | Cadastrar, editar, testar, pausar e excluir nas três integrações |
| Admin | Administrador | Todas as integrações, perfis e atribuições |

Abra **Dunker · Integrações → Permissões** para criar perfis e selecionar **Sem acesso**, **Consultar** ou **Editar e testar** em cada integração. Você pode alterar o padrão de Viewer/Editor para novos usuários ou atribuir um perfil específico a um usuário existente. Por exemplo, um Viewer pode receber edição apenas de links, sem ganhar edição de dashboards.

A API consulta a sessão, organização e papel atuais no Grafana em cada operação; logout, troca de papel ou política revogam o acesso na próxima operação. Admin da organização configurada sempre administra permissões. A política fica em `config/access/private/policy.json` e é preservada nas atualizações. `GRAFANA_ORG_ID=1` no `.env` define a organização proprietária. Outras organizações não acessam os cadastros globais.

**Este controle protege as configurações das integrações. Não separa os dados dos dashboards por cliente.** Filtros de cliente não são isolamento de acesso. Os segredos salvos não são exibidos de volta na tela de consulta.

Veja `docs/PERMISSOES-GRAFANA.md` para o passo a passo e validação no servidor.

## Operação depois da atualização

Na pasta instalada:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\INICIAR-PROJETO.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\PARAR-PROJETO.ps1
```

No Ubuntu, `bash iniciar-projeto.sh` e `bash parar-projeto.sh`. Para investigar:

```text
docker compose -f compose.separado.yaml ps
docker compose -f compose.separado.yaml logs --tail 100 admin grafana sharepoint sharepoint-prometheus snmp prometheus
```

Não use `down -v` para atualizar: isso remove volumes. Para máquinas com Alloy, o pacote mantém os utilitários `scripts/gerar-agente.py` e `scripts/importar-inventario.py`.

## Revisão desta entrega

O código e os pacotes anteriores foram revisados e consolidados. Os testes de atualização cobrem base sem addons, instalação nova, preservação de credenciais/inventário/volumes, complementos existentes, repetição sem duplicação e restauração dos arquivos. Os testes dos coletores usam respostas simuladas e os testes de interfaces SNMP usam um agente de teste local.

Resultados dos testes desta revisão estão em `docs/VALIDACAO.md`. Não houve coleta real no tenant do cliente nem aplicação remota no SRV-DUNKER.

Esta entrega não foi executada no SRV-DUNKER, em Grafana real nem em um tenant Microsoft 365 real. A revisão da instalação efetiva ocorre quando você executar o script e estará nos relatórios. Docker/pwsh não estão disponíveis no ambiente onde este ZIP foi preparado; as validações reais dessas ferramentas são feitas no servidor pelo instalador.
