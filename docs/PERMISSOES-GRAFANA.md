# Configurações dentro do Grafana — 1.4.0

## Instalar no SRV-DUNKER

Extraia o ZIP em Downloads, separado da instalação. Na pasta que contém `ATUALIZAR-PROJETO.ps1`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ATUALIZAR-PROJETO.ps1 -Projeto "C:\Users\VitorBrabodaSilvaDun\Docker\dunker-monitor"
```

O instalador revisa os arquivos e containers, faz backup, aplica as mudanças e reinicia os serviços. Inventário, credenciais e volumes existentes são preservados. Não copie manualmente a pasta config sobre a instalação. O pacote continua usando o Compose único `compose.separado.yaml` para containers separados.

Entre em `http://172.16.27.51:8443/` e abra **Dunker · Integrações**. As páginas ficam dentro da navegação do Grafana:

- Links: `/a/dunker-integracoes-app/links`.
- SNMP: `/a/dunker-integracoes-app/snmp`.
- SharePoint: `/a/dunker-integracoes-app/sharepoint`.
- Permissões: `/a/dunker-integracoes-app/permissoes`.

Se o plugin não estiver visível, abra Administração → Plugins e dados → Plugins, procure Dunker · Integrações e habilite. O script tenta habilitar usando a conta admin do arquivo de senha; se a senha real tiver mudado na interface, use esta ativação manual. Recarregue a página com Ctrl+F5 após a atualização.

## Criar usuários e aplicar perfis

1. Como administrador do servidor Grafana, abra Administração → Usuários e acesso → Usuários e crie a conta.
2. Na organização principal, selecione Viewer, Editor ou Admin para o usuário. A edição de papéis também está na página `/org/users`.
3. O usuário já recebe o perfil automático da central. Não precisa de outra senha ou token.

| Papel da organização | Perfil automático inicial | Configurações |
|---|---|---|
| Viewer | Consulta | Consulta nas três integrações, detalhes e exportação SharePoint |
| Editor | Operador | Consulta, cadastro, edição, diagnóstico, pausa e exclusão |
| Admin | Administrador | Todas as operações e gestão de perfis |

Criar usuários no servidor exige permissão de administrador do servidor Grafana; Admin de uma organização pode gerenciar os usuários da organização conforme as permissões do Grafana. O campo que determina o perfil automático é o **papel na organização**.

## Personalizar

Na guia Permissões:

1. Clique em Criar perfil, dê um nome e selecione Sem acesso, Consultar ou Editar e testar em cada integração.
2. Para aplicação automática, escolha os perfis padrão de Viewer e Editor.
3. Para uma exceção, selecione o perfil na linha do usuário. Automático pelo papel Grafana remove a exceção.
4. Clique em Salvar permissões. Recarregue a tela após criar novos usuários no Grafana.

Exemplos: “Somente dashboards” bloqueia toda a central; “Técnico de links” edita links e consulta SNMP; “Gestor M365” edita SharePoint e não acessa as outras configurações. Admin mantém acesso completo para evitar bloqueio administrativo.

Os perfis da central não mudam o papel do Grafana nem as permissões de dashboards. Um Viewer pode editar integrações selecionadas e continuar sendo Viewer nos dashboards. Esses controles não isolam métricas por cliente: os cadastros são globais na organização proprietária. Para clientes externos, configure separadamente a visibilidade e o isolamento dos dados.

## Funcionamento e persistência

A API recebe o cookie da sessão do Grafana e verifica `/api/user` e `/api/user/orgs` a cada operação. Não aceita nome, papel, cabeçalhos de identidade ou senha admin enviados pelo navegador como autorização. O logout, mudança do papel ou de um perfil é aplicado na próxima operação; a navegação visual é atualizada ao recarregar a página. Falha de verificação bloqueia o acesso.

A política é salva atomicamente em `config/access/private/policy.json` e preservada nas atualizações. Se o arquivo ainda não existir, são usados os padrões da tabela. O `.env` contém `GRAFANA_ORG_ID=1`; outras organizações são bloqueadas porque os inventários e coletores atuais são compartilhados. Os segredos SNMP e Microsoft não são retornados em consultas. O token interno SharePoint fica somente no servidor. As antigas rotas de proxy do plugin foram removidas.

`/monitoramento/` e `/monitoramento/sharepoint/` redirecionam para as páginas do plugin. A API de configurações continua sob `/monitoramento/api/`, usando a sessão Grafana e autorização no servidor; o serviço admin não publica porta própria.

## Conferir após instalar

- Viewer: abrir as três páginas, consultar detalhes e confirmar que cadastro, pausa, exclusão e testes não estão disponíveis.
- Editor: cadastrar um alvo de teste, editar, testar, pausar e excluir.
- Admin: criar um perfil com edição de links e Sem acesso nas outras integrações; atribuir a um Viewer e verificar o resultado.
- Revogar um perfil e confirmar que a próxima operação do usuário já conectado é recusada.
- Sair do Grafana e confirmar que a API pede login novamente.
- Conferir SharePoint com credenciais reais e SNMP com o equipamento real.

O ambiente de desenvolvimento não tem Docker/Grafana em execução. A integração com a versão real do Grafana, a política de cookies do proxy e os equipamentos do SRV-DUNKER precisam desta conferência após a instalação. Os testes automatizados usam um servidor HTTP que simula as APIs de sessão do Grafana e dados simulados para a interface.
