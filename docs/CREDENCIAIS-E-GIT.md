# Credenciais e Git

Aplique este pacote sobre a raiz do projeto. Os exemplos não contêm senhas reais. Os arquivos locais existentes são preservados.

O .gitignore exclui .env, senhas, chaves, certificados, acessos privados, agentes gerados, backups e as configurações locais do SNMP e Caddy que contêm comunidade e hash de autenticação. Os arquivos .example devem conter apenas placeholders: a exceção permite versioná-los.

## Arquivos que precisam ficar locais

| Exemplo para Git | Arquivo local | Finalidade |
|---|---|---|
| .env.example | .env | IP, porta e variáveis locais |
| config/secrets/grafana_admin_password.example | config/secrets/grafana_admin_password | Senha inicial Grafana e login do cadastro |
| config/secrets/grafana_secret_key.example | config/secrets/grafana_secret_key | Criptografia do Grafana |
| config/secrets/ingest_password.example | config/secrets/ingest_password | Senha dos agentes Alloy |
| config/secrets/snmp_community.example | config/secrets/snmp_community | Comunidade SNMP v2c |
| config/secrets/credentials.json.example | config/secrets/credentials.json | Registro auxiliar de credenciais |
| config/caddy/Caddyfile.example | config/caddy/Caddyfile | Rotas e hash da senha de ingestão |
| config/snmp.yml.example | config/snmp.yml | Módulos e comunidade SNMP |
| config/snmp-v3.yml.example | Perfil em config/snmp.yml | Usuário, senha de autenticação e senha de privacidade SNMP v3 |

Em uma instalação existente, não copie exemplos por cima dos arquivos reais. Em um clone novo, copie cada exemplo para o nome local da tabela e preencha os valores antes de iniciar Docker. O credentials.json é auxiliar; os serviços leem os arquivos individuais. Mantenha os valores consistentes.

A comunidade em snmp.yml deve corresponder a snmp_community e ao equipamento. Nos dois blocos basic_auth do Caddyfile, coloque o mesmo hash bcrypt da senha ingest_password. Para gerar o hash sem colocar a senha no histórico do comando, use um terminal interativo:

```powershell
docker run --rm -it caddy:2.11.4 caddy hash-password
```

Guarde senhas no 1Password. A chave grafana_secret_key de uma instalação existente deve ser preservada com seu banco; não a troque apenas para configurar estes exemplos.

## Retirar arquivos já rastreados

.gitignore não remove arquivos que já estão no Git. No PowerShell, na raiz do projeto, execute:

```powershell
$ignorados = @(git ls-files -ci --exclude-standard)
if ($ignorados.Count -gt 0) { git rm --cached --ignore-unmatch -- $ignorados }
git status --short
```

Isso retira do próximo commit os arquivos rastreados que agora são ignorados, mantendo-os no computador. Revise git status antes de commitar. O histórico antigo continua contendo os valores que já foram publicados: remover o rastreamento não apaga histórico nem revoga senhas.

O .gitignore usa nomes e caminhos, não examina o conteúdo de todo arquivo. Uma senha colocada em um código ou .example poderá ser enviada ao Git; não coloque valores reais nesses arquivos.
