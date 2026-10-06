[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Projeto,[switch]$NovaInstalacao,[switch]$SomenteVerificar)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'scripts/windows-common.ps1')
$package=$PSScriptRoot
if($NovaInstalacao){[IO.Directory]::CreateDirectory($Projeto)|Out-Null}
if(!(Test-Path -LiteralPath $Projeto -PathType Container)){throw 'Pasta do projeto ausente. Confira -Projeto ou use -NovaInstalacao para criar uma instalacao nova.'}
$root=(Resolve-Path -LiteralPath $Projeto).Path
if(!$SomenteVerificar -and (Normalize-DockerPath $root) -eq (Normalize-DockerPath $package)){throw 'Extraia o ZIP em outra pasta. -Projeto deve apontar para a instalacao no servidor.'}
if(!(Get-Command docker -ErrorAction SilentlyContinue)){throw 'Execute no SRV-DUNKER com Docker Desktop acessivel.'}
$dockerType=& docker info --format '{{.OSType}}'
if($LASTEXITCODE -ne 0 -or $dockerType -ne 'linux'){throw 'Docker deve estar em execucao no modo de containers Linux.'}
$report=Join-Path $root ('diagnostico/revisao-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,6))
$reportRelative=$report.Substring($root.Length).TrimStart([char[]]'\/').Replace('\','/')
$before=@(Get-DunkerInventory $root);Write-DockerReport $report 'antes' $before
$toolingImage='vitorbrabodunker/dunker-monitor-separado:1.2.0'
function Manager([string[]]$Arguments){
 & docker run --rm --entrypoint python3 --mount "type=bind,source=$root,target=/projeto" --mount "type=bind,source=$package,target=/pacote,readonly" $toolingImage /pacote/scripts/project_manager.py @Arguments --project /projeto --package /pacote
 if($LASTEXITCODE -ne 0){throw 'A revisao/preparacao falhou. Confira a mensagem acima e os relatorios.'}
}
Manager @('inspect','--output',('/projeto/'+$reportRelative),'--stage','antes')
if($SomenteVerificar){Write-Host "Revisao concluida: $report";exit 0}
$matches=@($before|Where-Object{(Normalize-DockerPath $_.WorkingDirectory) -eq (Normalize-DockerPath $root) -and $_.Service -ne 'monitor'})
$other=@($before|Where-Object{(Normalize-DockerPath $_.WorkingDirectory) -ne (Normalize-DockerPath $root) -and $_.Status -eq 'running'})
if($matches.Count -eq 0 -and $other.Count -gt 0){throw "Os containers Dunker ativos apontam para outra pasta: $($other[0].WorkingDirectory). Use essa pasta em -Projeto. Relatorio: $report"}
$names=@($matches|ForEach-Object{$_.Project}|Sort-Object -Unique)
if($names.Count -gt 1){throw "Mais de um projeto Compose usa essa pasta. Consulte $report antes de aplicar."}
if(@($before|Where-Object{$_.Service -eq 'monitor' -and $_.Status -eq 'running'}).Count -gt 0){throw "Foi detectado o modo de container unico ativo. Este pacote usa containers separados; consulte $report antes de migrar."}
# Reject undiscovered external overrides instead of silently ignoring them.
foreach($item in $matches){
 foreach($file in ($item.ComposeFiles -split ',')){
  if($file -and [IO.Path]::GetFileName($file) -notin @('compose.separado.yaml','compose.integracoes.yaml','compose.sharepoint.yaml')){throw "Compose adicional em uso: $file. Relatorio salvo em $report; esse complemento precisa ser integrado antes de aplicar."}
 }
}
$argsApply=@('apply')
if($NovaInstalacao){$argsApply+='--new'}
if($names.Count -eq 1){$argsApply+=@('--compose-name',$names[0])}
Manager $argsApply
Push-Location -LiteralPath $root
try{
 $pending=Join-Path $root 'config/secrets/ingest_hash.pending'
 if(Test-Path -LiteralPath $pending){
  $ingestPassword=[IO.File]::ReadAllText((Join-Path $root 'config/secrets/ingest_password')).Trim()
  $hashOutput=& docker run --rm --entrypoint caddy caddy:2.11.4 hash-password --plaintext $ingestPassword
  $ingestPassword=$null
  if($LASTEXITCODE -ne 0){throw 'Falha ao preparar autenticacao Caddy.'}
  $hash=($hashOutput|Where-Object{$_ -match '^\$2[aby]\$'})|Select-Object -Last 1
  if(!$hash){throw 'Caddy nao devolveu um hash valido.'}
  [IO.File]::WriteAllText((Join-Path $root 'config/secrets/ingest_hash'),$hash+"`n",(New-Object System.Text.UTF8Encoding($false)))
  Manager @('finalize-hash')
 }
 & docker compose -f compose.separado.yaml config --quiet
 if($LASTEXITCODE -ne 0){throw 'Compose consolidado invalido.'}
 & docker compose -f compose.separado.yaml run --rm --no-deps --entrypoint /bin/promtool prometheus check config /etc/dunker/prometheus/separado.yml
 if($LASTEXITCODE -ne 0){throw 'Configuracao/regras do Prometheus principal invalidas.'}
 & docker compose -f compose.separado.yaml run --rm --no-deps --entrypoint /bin/promtool sharepoint-prometheus check config /etc/dunker/sharepoint/prometheus.yml
 if($LASTEXITCODE -ne 0){throw 'Configuracao/regras do SharePoint invalidas.'}
 & docker compose -f compose.separado.yaml run --rm --no-deps --entrypoint caddy caddy validate --config /etc/dunker/caddy/Caddyfile --adapter caddyfile
 if($LASTEXITCODE -ne 0){throw 'Caddyfile invalido.'}
}catch{
 Manager @('rollback')
 Write-Warning 'Validacao falhou. Os arquivos foram restaurados antes de ativar os servicos; relatorios e backup foram preservados.'
 throw
}finally{Pop-Location}
# Restart services because changes inside directory bind mounts do not trigger recreation.
# After a partial startup, retain applied files for consistent recovery.
Push-Location -LiteralPath $root
try{
 & docker compose -f compose.separado.yaml up -d --no-build
 if($LASTEXITCODE -ne 0){throw "Arquivos preparados, mas algum container nao iniciou. Confira $report e docker compose -f compose.separado.yaml logs --tail 100. O backup foi preservado."}
 & docker compose -f compose.separado.yaml restart
 if($LASTEXITCODE -ne 0){throw 'Falha ao reiniciar os servicos para carregar os arquivos atualizados. Confira os logs.'}
 & docker compose -f compose.separado.yaml exec -T admin python3 /opt/dunker/sharepoint_activate.py
 if($LASTEXITCODE -ne 0){Write-Warning 'Ativacao do plugin pendente; ative Dunker Integracoes no menu de plugins do Grafana.'}
 & docker compose -f compose.separado.yaml ps
}finally{Pop-Location}
$after=@(Get-DunkerInventory $root);Write-DockerReport $report 'depois' $after
Manager @('inspect','--output',('/projeto/'+$reportRelative),'--stage','depois')
Write-Host "Projeto completo atualizado. Revisao antes/depois: $report"
Write-Host 'Agora use somente compose.separado.yaml. Credenciais novas, se criadas, estao em config/secrets; guarde no seu cofre.'
