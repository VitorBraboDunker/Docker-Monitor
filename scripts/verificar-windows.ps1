param(
    [ValidateSet('separado','unico')][string]$Modo = 'separado',
    [string]$Endereco = 'http://127.0.0.1:8443'
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$arquivo = "compose.$Modo.yaml"
$falhas = 0
function Verificar-Comando([string]$Nome, [string[]]$Argumentos) {
    Write-Host "`n$Nome" -ForegroundColor Cyan
    & docker @Argumentos
    if ($LASTEXITCODE -ne 0) { $script:falhas++; Write-Host 'FALHOU' -ForegroundColor Red }
}
try { & docker info --format '{{.ServerVersion}}'; if ($LASTEXITCODE -ne 0) { throw 'Docker indisponivel' } }
catch { Write-Error 'Abra o Docker Desktop no SRV-DUNKER e aguarde o mecanismo iniciar.'; exit 1 }
Verificar-Comando 'Validacao do Compose' @('compose','-f',$arquivo,'config','--quiet')
Verificar-Comando 'Estado dos containers' @('compose','-f',$arquivo,'ps','--all')
if ($Modo -eq 'separado') {
    Verificar-Comando 'Validacao do proxy Caddy' @('compose','-f',$arquivo,'exec','-T','caddy','caddy','validate','--config','/etc/dunker/caddy/Caddyfile','--adapter','caddyfile')
    Verificar-Comando 'Validacao Prometheus e regras' @('compose','-f',$arquivo,'exec','-T','prometheus','promtool','check','config','/etc/dunker/prometheus/separado.yml')
    Verificar-Comando 'Sintaxe do inventario' @('compose','-f',$arquivo,'exec','-T','ping','python3','-c',"import json; d=json.load(open('/etc/dunker/targets/inventory.json')); assert isinstance(d,list); print(str(len(d))+' alvos no inventario')")
} else {
    Verificar-Comando 'Validacao do proxy Caddy' @('compose','-f',$arquivo,'exec','-T','monitor','caddy','validate','--config','/etc/dunker/caddy/Caddyfile','--adapter','caddyfile')
    Verificar-Comando 'Validacao Prometheus e regras' @('compose','-f',$arquivo,'exec','-T','monitor','promtool','check','config','/etc/dunker/prometheus/unico.yml')
}
$Endereco = $Endereco.TrimEnd('/')
try {
    $saude = Invoke-RestMethod "$Endereco/api/health" -TimeoutSec 10
    if ($saude.database -ne 'ok') { throw 'Banco nao esta pronto' }
    Write-Host "`nGrafana e banco: OK" -ForegroundColor Green
} catch { $falhas++; Write-Host 'Falha no acesso ao Grafana. Confira endereco, porta, firewall e logs.' -ForegroundColor Red }
try {
    Invoke-WebRequest "$Endereco/monitoramento/api/monitors" -UseBasicParsing -TimeoutSec 10 | Out-Null
    $falhas++; Write-Host 'ERRO: cadastro acessivel sem autenticacao.' -ForegroundColor Red
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) {
        Write-Host 'Cadastro exige autenticacao: OK' -ForegroundColor Green
    } else { $falhas++; Write-Host 'Falha na rota do cadastro.' -ForegroundColor Red }
}
Write-Host "`nFalhas detectadas: $falhas"
Write-Host "Grafana: $Endereco/"
Write-Host "Cadastro: $Endereco/monitoramento/"
Write-Host 'Teste um IP pela tela e confirme a coleta no Explore do Grafana.'
exit ([int]($falhas -gt 0))
