# Cadastro de verificações — versão 1.2.0

Criticidade removida do formulário, das novas configurações e das métricas. Todos os monitores contribuem igualmente para o estado geral. Dados antigos recebem normalização ao iniciar o cadastro, preservando IDs existentes.

Tipos disponíveis:
- Ping ICMP IPv4: quantidade de pacotes, intervalo entre pacotes, timeout por pacote, perda e latência média.
- HTTP/HTTPS: URL, GET ou HEAD, seguir redirecionamentos, código esperado (0 permite qualquer 2xx). Certificados HTTPS são validados.
- TCP: host IPv4/IPv6/hostname e porta; verifica abertura da conexão.
- DNS: servidor, porta, nome consultado e registro A/AAAA/CNAME/MX/TXT/NS; UDP com tentativa TCP quando a resposta está truncada. Sucesso exige rcode 0 e ao menos uma resposta.

Todos possuem frequência, timeout, cliente, unidade, provedor/serviço, estado ativo/pausado e teste imediato. A frequência controla o coletor agendado; o Blackbox mantém a checagem rápida separada de ICMP. As regras gerais incluem DNS, HTTP e TCP. Limites de perda e latência continuam específicos de ICMP.

HTTP não possui autenticação, cabeçalhos personalizados, corpo de requisição, comparação do corpo de resposta ou navegador/script. DNS não compara o valor esperado do registro. Os testes partem do SRV-DUNKER; não há seleção de sondas geográficas. Portanto, esta é uma tela funcional inspirada no fluxo do Synthetic Monitoring, sem equivalência completa de funcionalidades. O timeout HTTP é de operações de rede; uma cadeia de redirecionamentos pode levar mais tempo.

## Atualizar

Extraia o pacote de atualização na raiz existente. Ele preserva .env, senhas, inventários e configurações locais de Caddy/SNMP. Para o modo separado:

```powershell
docker compose -f compose.separado.yaml up -d --build
```

Para o modo único (escolha somente um):

```powershell
docker compose -f compose.unico.yaml up -d --build
```

Os Composes agora apontam para vitorbrabodunker/dunker-monitor-separado:1.2.0 e vitorbrabodunker/dunker-monitor-unico:1.2.0. As imagens precisam ser construídas localmente com --build; não foram publicadas no Docker Hub por esta atualização.

Abra http://172.16.27.51:8443/monitoramento/ e atualize a página com Ctrl+F5. Login continua admin e senha do arquivo config/secrets/grafana_admin_password.

## Validação

Passaram os testes HTTP (código e redirecionamento), conexão TCP e DNS com servidores locais de teste, validação de parâmetros, persistência de protocolos e emissão de métricas. Os testes anteriores de autenticação e CRUD também passaram. Compilação Python, sintaxe JavaScript e parsing YAML passaram.

Docker, regras via promtool, validação visual no navegador e destinos reais do cliente não foram executados neste ambiente. ICMP real permanece bloqueado aqui. Após subir, use Testar agora e confira dnk_check_success no Explore do Grafana, além de logs e /rules do Prometheus.
