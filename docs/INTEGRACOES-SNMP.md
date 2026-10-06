# Dunker Monitor — central de integrações externas

Componente integrado ao Dunker Monitor completo 1.4.0. Instalação e revisão usam o instalador único descrito no README principal.

## O que está pronto

- Tela `/a/dunker-integracoes-app/snmp` com abas **Links e disponibilidade** e **Firewalls e roteadores**.
- Cadastro/edição ICMP, HTTP/HTTPS, TCP e DNS; frequência, timeout e demais parâmetros preservados. Sem campo de criticidade.
- Cadastro/edição, pausa e exclusão de equipamentos SNMPv2c e SNMPv3 authPriv.
- Teste de conexão e descoberta de interfaces, com seleção das WANs e download/upload contratados por interface.
- Perfil SonicWall: IF-MIB + SYSTEM para tráfego/uptime; módulo separado para CPU/RAM.
- Perfil MikroTik: IF-MIB + SYSTEM e HOST-RESOURCES para CPU/RAM, quando expostos pelo dispositivo.
- Perfil genérico para tráfego/uptime, com OIDs opcionais de utilização de CPU/RAM em percentual.
- Quatro dashboards: Firewalls e roteadores, Detalhes do firewall, Clientes — Links e firewalls, Cliente — Links e firewalls.
- Credenciais separadas do inventário e do conteúdo dos dashboards; recarga nativa do SNMP Exporter após salvar.

O pacote atualiza `dnk-firewalls` preservando seu UID. Os dashboards `dnk-geral`, `dnk-links` e `dnk-links-geral` não são substituídos. A nova visão combinada de clientes é adicional. Ela usa as regras `dnk:link_state` do pacote de dashboards de clientes já entregue; caso ainda não tenha instalado aquele pacote, a visão combinada mostrará somente os firewalls.

## Instalação

Este componente já está incluído no pacote completo 1.4.0. Use `ATUALIZAR-PROJETO.ps1` no Windows ou `atualizar-projeto.sh` no Ubuntu, conforme o README principal. Não há complemento anterior obrigatório. Todos os serviços usam somente `compose.separado.yaml`.

## Comandos depois da atualização

Na pasta do projeto, use **somente `compose.separado.yaml`**:

```powershell
docker compose -f compose.separado.yaml up -d --no-build
docker compose -f compose.separado.yaml ps
docker compose -f compose.separado.yaml logs --tail 100 admin snmp prometheus
```

A imagem Python publicada continua na versão 1.2.0. Este pacote monta o backend e a página novos a partir de arquivos locais; não publica imagens no Docker Hub. Os arquivos novos já fazem parte do projeto consolidado. Após alterar as fontes em `config/admin/`, reconstrua o plugin com `python3 scripts/build-plugin.py`, reinicie o Grafana e recarregue a página. Alterações do Python exigem recriar os serviços `admin` e/ou `ping` com somente `compose.separado.yaml` (`up -d --force-recreate --no-build admin ping`).

## Preparar o SonicWall

Primeiro identifique o modelo e a versão de SonicOS. Os nomes dos menus abaixo são os documentados para 6.5 e 7; firmware antigo pode ter menus e recursos diferentes.

| Etapa | SonicOS 6.5 | SonicOS 7 |
| --- | --- | --- |
| Habilitar SNMP | MANAGE → Appliance → SNMP | DEVICE → Settings → SNMP |
| Configurar a interface de consulta | MANAGE → Network → Interfaces | NETWORK → System → Interfaces |
| Conferir regras de acesso | MANAGE → Rules → Access Rules | POLICY → Rules and Policies → Access Rules |

1. Entre na administração do SonicWall e ative **Enable SNMP**. Salve em Accept/Apply.
2. Abra Configure e escolha a versão suportada. Prefira **SNMPv3 authPriv**, com um usuário de monitoramento, protocolo de autenticação e senha, protocolo de criptografia e senha. Use os mesmos parâmetros no cadastro da central. As senhas precisam ter pelo menos oito caracteres. Para SNMPv2c, configure uma comunidade **GET / somente leitura**; ela precisa ser igual à informada na central. Não é a senha de login administrativo do SonicWall.
3. Caso o firmware exponha `Mandatory Require SNMPv3`, habilite somente se vai usar v3; ele impede os testes com v2c.
4. Na interface pela qual o servidor vai consultar o firewall — normalmente LAN/X0 ou a interface alcançável pela VPN — marque **SNMP** na área Management. Salve. Não é necessário habilitar SNMP na WAN pública para consultar as métricas da WAN por meio da LAN/VPN.
5. Autorize **UDP 161** da origem real do coletor para o endereço de gerenciamento do firewall. Se o coletor estiver na mesma rede e o SRV-DUNKER mantiver `172.16.27.51`, esse é o endereço de origem esperado; confirme nos logs/captura, pois Docker Desktop, VPN ou NAT podem alterar a origem observada. Restrinja a regra a essa origem e ao destino específico.
6. Não é necessário informar um destino de traps ou liberar UDP 162 para esta coleta. O servidor consulta periodicamente o equipamento; esta entrega não recebe traps.
7. Salve e faça o teste pela central.

Para um firewall em outro cliente, precisa existir uma rota privada entre o coletor e o IP de gerenciamento. Uma VPN acessível pelo Windows não garante automaticamente que o container Docker alcance a mesma rede: o teste da central confirma o caminho do container. Tailscale somente no SRV-DUNKER também não cria acesso à LAN remota; é necessário subnet router/rota anunciada no local remoto ou outra VPN com essa rota.

Referência oficial de habilitação SNMPv3 e interfaces:
https://www.sonicwall.com/ja-jp/support/knowledge-base/kA1VN0000000CMM0A2

MIBs específicas do modelo podem ser obtidas no MySonicWall:
https://www.sonicwall.com/es-mx/support/knowledge-base/where-can-i-download-the-snmp-mib-files/kA1VN0000000GTN0A2

## Cadastrar na central

1. Abra o endereço atual do Grafana, acrescentando **`/a/dunker-integracoes-app/snmp`**. Mantenha a porta que seu projeto já utiliza.
2. Use seu usuário do Grafana. O perfil SNMP precisa permitir edição para cadastrar ou testar; consulta permite abrir os detalhes. Admin ajusta os perfis em Dunker · Integrações → Permissões.
3. Selecione **Firewalls e roteadores → Novo equipamento SNMP**.
4. Preencha nome, cliente, unidade, fabricante, modelo/firmware e IP acessível pelo servidor. Use o IP da interface de gerenciamento, sem `http://`, `https://`, porta ou caminho. A porta tem campo próprio.
5. Selecione v2c ou v3 e informe as credenciais. Na edição, campos de credenciais vazios mantêm o valor salvo. Para trocar de versão, informe os parâmetros da nova versão.
6. Comece com frequência **60 s**, timeout total **20 s** e porta **161**. O timeout precisa ser menor que a frequência. A frequência disponível é 30 a 120 s, compatível com a janela de identificação de dados recentes dos dashboards existentes. A tentativa individual SNMP usa 3 s e uma repetição, dentro do limite total.
7. Clique **Testar e descobrir interfaces**. Esse teste não salva o cadastro.
8. Marque as interfaces desejadas, como X1/X2 para os links WAN. Se não marcar nenhuma, os gráficos mostram todas, e interfaces sem link não afetam o estado geral.
9. Informe a banda contratada de cada interface, se quiser o percentual de utilização. Ex.: download 300 Mbps e upload 100 Mbps. Não use a velocidade física de 1 Gbps da porta como banda contratada.
10. Salve e aguarde as primeiras coletas. Gráficos de tráfego precisam de pelo menos duas amostras; a janela usual é cinco minutos.

O sentido de entrada/saída é relativo à interface do firewall. Na WAN, entrada normalmente corresponde ao download e saída ao upload. Em uma LAN, esse significado pode se inverter; identifique a interface correta antes de cadastrar as capacidades.

Cadastros SNMP antigos, feitos manualmente em `snmp.json`, são preservados. Eles não aparecem como editáveis na nova central. Para migrar um deles, faça backup e remova somente sua entrada manual quando o cadastro novo estiver validado; manter ambos simultaneamente pode gerar coletas duplicadas. O pacote não converte automaticamente credenciais antigas.

## CPU e memória

O perfil SonicWall consulta:

| Métrica | OID escalar |
| --- | --- |
| CPU utilizada (%) | `1.3.6.1.4.1.8741.1.3.1.4.0` |
| RAM utilizada (%) | `1.3.6.1.4.1.8741.1.3.1.4.0` |

Esses OIDs já estavam no perfil do projeto e correspondem à MIB SonicWall de estatísticas. Precisam ser confirmados no equipamento real. Se ele não responder, o teste informa que CPU/RAM não estão disponíveis e mantém a coleta de interfaces. Dados ausentes aparecem como “Não exposta”, não como utilização zero.

Para outro fabricante, os campos avançados aceitam OIDs que retornem **percentual utilizado de 0 a 100**, com `.0` no final para escalares. Não use nesses campos um OID de bytes livres, temperatura, média de carga ou tabela por núcleo. Valores de bytes exigem um perfil com cálculo próprio.

O perfil MikroTik usa carga média dos processadores e utilização de armazenamento identificado como RAM/main memory. Verifique se o firmware expõe HOST-RESOURCES; outros modelos podem exigir um módulo específico.

## Dashboards e cores

Em Grafana → Dashboards, abra:

- **Dunker | Firewalls e roteadores**: um indicador por equipamento; clique para abrir os detalhes.
- **Dunker | Detalhes do firewall**: CPU, RAM, uptime do agente SNMP, tráfego por interface, percentual contratado e estado das interfaces.
- **Dunker | Clientes - Links e firewalls**: visão adicional que combina os componentes por cliente.
- **Dunker | Cliente - Links e firewalls**: links e equipamentos do cliente, com atalhos de detalhe.

Os novos dashboards têm o atalho **Configurações externas**. Os atalhos antigos de cadastro continuam abrindo a mesma central. Não foi instalado um plugin de formulários no Grafana: plugins como Business Forms são possíveis, mas também precisam de uma API de backend. A central própria mantém a configuração no mesmo endereço, com um formulário completo e protegido.

| Cor | Estado dos firewalls |
| --- | --- |
| Verde | Coleta de interfaces disponível, sem limites excedidos |
| Cinza | Cadastro ativo sem coleta recente |
| Amarelo | Média de CPU acima de 85% ou RAM acima de 90% na janela de 5 minutos |
| Laranja | Média de CPU acima de 95%, RAM acima de 97%, ou interface selecionada não operacional |
| Vermelho | Coleta SNMP de interfaces falhou |

O vermelho indica falha de coleta; pode ser rota, credencial ou bloqueio, e não prova sozinho que o firewall desligou. Falta de suporte a OIDs de CPU/RAM não transforma um equipamento com interfaces respondendo em “desligado”. Os alertas de CPU/RAM usam persistência de 5 minutos e seguem o Alertmanager já configurado; não foi criado novo destinatário.

Contadores de 64 bits são preferidos. Há fallback para 32 bits quando os contadores de 64 bits não existem; links rápidos com contadores de 32 bits podem sofrer múltiplas voltas entre coletas. Por exemplo, cerca de 34 segundos bastam para dar uma volta em um contador de octetos a 1 Gbps. Nesse caso, é necessário suporte a 64 bits para medir corretamente.

## Arquivos, persistência e recuperação

As credenciais ficam em `config/integracoes/private/credentials.json` e na configuração gerada `snmp-managed.yml`; os arquivos escritos pelo backend usam permissão 0600 em sistemas que suportam esse controle. Essa proteção é por permissões de arquivo, **sem criptografia do conteúdo em repouso**. No Windows, proteja a pasta com ACLs e acesso restrito. O instalador acrescenta a pasta privada ao `.gitignore`.

Não coloque comunidades/senhas em dashboards nem envie a pasta privada ao GitHub. Guarde backups dessa pasta de forma protegida e mantenha as credenciais no 1Password. O arquivo de módulos e o HTML não contêm credenciais reais. O SNMP Exporter lê tanto a configuração anterior quanto a nova, preservando perfis antigos; sua recarga permanece acessível somente pela rede interna dos containers, sem porta nova publicada.

As configurações têm autorização por usuário e integração na organização principal. Esse controle não isola os dados dos dashboards por cliente. Veja `PERMISSOES-GRAFANA.md` para o gerenciamento de acesso.

Se precisar restaurar uma instalação, pare os serviços administrativos, restaure os arquivos do backup criado pelo instalador e use o Compose anterior. Para desfazer cadastros feitos após a instalação, restaure também o inventário, `snmp.json` e a pasta privada do mesmo ponto de backup. Não use `docker compose down -v`: isso removeria volumes de dados.

## Validação

A validação do pacote consolidado está em `VALIDACAO.md`. Os testes agora usam a biblioteca YAML incluída no pacote. Para cenários com o binário real do exporter, defina `SNMP_EXPORTER_BIN` com o caminho do executável; para cenários Prometheus, execute `promtool test rules tests/snmp-rules.yml`.

Referências de arquitetura:
https://github.com/prometheus/snmp_exporter
https://prometheus.io/docs/prometheus/latest/configuration/configuration/
