# Validação - 29/09/2026

## Executado com sucesso

- Download das imagens oficiais Linux/amd64 com verificação SHA-256 dos blobs e das camadas descompactadas (diff IDs).
- Leitura de todos os YAML/JSON e verificação de sintaxe dos scripts shell.
- `promtool check config` para as duas variantes e `promtool check rules` para as 25 regras.
- `promtool test rules`: estados saudável (0), indisponível (3) e agente ausente (1). A ausência de dados não se transforma em verde.
- `amtool check-config` para Alertmanager; `alloy validate` para a configuração central; `loki -verify-config`; `caddy validate`.
- Inicialização dos nove serviços como processos Linux nativos, em diretórios temporários e endpoints locais, usando os binários extraídos das imagens.
- Endpoints de prontidão/saúde do Grafana, Prometheus, Alertmanager, Loki, Blackbox, SNMP Exporter, Alloy e exportador de ping.
- Acesso HTTPS com validação da CA, login administrativo do Grafana e provisionamento dos cinco dashboards.
- Rejeição de requisições sem credencial nos endpoints de ingestão de métricas e logs (HTTP 401).
- Avaliação das regras com saúde `ok` e recebimento real de métricas Linux enviadas pelo Alloy ao Prometheus via remote_write.
- Validação do checksum, correspondência de respostas (identificador/sequência/payload), rejeição de resposta incorreta e tratamento de erro de configuração do coletor ICMP.
- Geração das configurações de agentes; validação semântica do agente Linux e sintaxe do agente Windows (execução Windows pendente).

## Pendente na VM de destino

- `docker load` e subida pelo Docker Engine/Compose: não há daemon Docker executável neste ambiente. As imagens foram montadas no formato de arquivo Docker com camadas oficiais verificadas; não foram iniciadas como containers aqui.
- ICMP real: o ambiente de execução bloqueia sockets ICMP. As duas variantes configuram NET_RAW. O resultado aqui foi erro de coleta sem medir perda, como esperado nesse caso.
- SNMP em MikroTik/SonicWall reais, diferenças de MIB por firmware, tráfego WAN e permissões/rotas nas redes dos clientes.
- Execução de Alloy no Windows real e coleta dos contadores/eventos de cada versão instalada.
- Rotas, bridge/NAT, VPN, firewall da VM, volumes Docker e carga sustentada.
- Entrega de notificações externas: o receiver inicial não envia mensagens.
- Teste de restauração de backup em outra VM.

Os testes nativos validam configuração e comunicação entre serviços. Eles não equivalem à homologação completa dos containers nem dos equipamentos do cliente.
