[CmdletBinding()]
param([string]$Instalador='', [switch]$SubstituirConfiguracao)
$ErrorActionPreference='Stop'
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if(!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Execute este script no PowerShell como Administrador, no servidor que sera monitorado.'}
if(![Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64'){throw 'Este pacote requer Windows x64 (AMD64).'}
$source=Join-Path $PSScriptRoot 'config.alloy'
if(!(Test-Path -LiteralPath $source -PathType Leaf)){throw 'Extraia todos os arquivos do ZIP antes de executar.'}
$metadata=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'agente.json') -Raw|ConvertFrom-Json
$service=Get-Service -Name Alloy -ErrorAction SilentlyContinue
if($service -and !$SubstituirConfiguracao){throw 'Alloy ja esta instalado. Para substituir sua configuracao com backup, execute novamente com -SubstituirConfiguracao.'}
$directory=Join-Path $env:ProgramFiles 'GrafanaLabs\Alloy'
$target=Join-Path $directory 'config.alloy'
$regPath='HKLM:\SOFTWARE\GrafanaLabs\Alloy'
$backup=Join-Path $env:ProgramData ('DunkerMonitor\backups\alloy-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,6))
[IO.Directory]::CreateDirectory($backup)|Out-Null
# Restrict local backups, which can include prior service environment values.
& icacls $backup /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if($LASTEXITCODE -ne 0){throw 'Falha ao proteger a pasta de backup.'}
$oldRegistry=if(Test-Path $regPath){Get-ItemProperty -LiteralPath $regPath}else{$null}
$oldArguments=if($oldRegistry){@($oldRegistry.Arguments)}else{@()}
$oldEnvironment=if($oldRegistry){@($oldRegistry.Environment)}else{@()}
@{Arguments=$oldArguments;Environment=$oldEnvironment}|Export-Clixml -LiteralPath (Join-Path $backup 'service.xml')
$hadConfig=Test-Path -LiteralPath $target
if($hadConfig){Copy-Item -LiteralPath $target -Destination (Join-Path $backup 'config.alloy')}
# Preserve an existing custom config path as well as the standard config.
if($oldArguments.Count -gt 1 -and $oldArguments[0] -eq 'run' -and (Test-Path -LiteralPath $oldArguments[1] -PathType Leaf)){
 Copy-Item -LiteralPath $oldArguments[1] -Destination (Join-Path $backup 'config-original.alloy')
}
$wasRunning=$service -and $service.Status -eq 'Running'
$temp=Join-Path ([IO.Path]::GetTempPath()) ('dunker-alloy-'+[guid]::NewGuid().ToString('N'))
$secure=$null;$ingestPassword=$null;$changed=$false
$previousProcessPassword=$env:DNK_INGEST_PASSWORD
try{
 if(!$service){
  if(!$Instalador){
   [IO.Directory]::CreateDirectory($temp)|Out-Null
   [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
   $release=Invoke-RestMethod -Uri ('https://api.github.com/repos/grafana/alloy/releases/tags/v'+$metadata.alloy_version) -Headers @{'User-Agent'='DunkerMonitor-Alloy'}
   $asset=@($release.assets|Where-Object{$_.name -eq 'alloy-installer-windows-amd64.exe'})|Select-Object -First 1
   if(!$asset){$asset=@($release.assets|Where-Object{$_.name -eq 'alloy-installer-windows-amd64.exe.zip'})|Select-Object -First 1}
   if(!$asset){throw 'Instalador oficial nao localizado. Baixe-o em https://github.com/grafana/alloy/releases e use -Instalador com o caminho do EXE.'}
   $prefix='https://github.com/grafana/alloy/releases/download/v'+$metadata.alloy_version+'/'
   if(!$asset.browser_download_url.StartsWith($prefix,[StringComparison]::Ordinal)){throw 'URL do instalador oficial inesperada.'}
   $download=Join-Path $temp $asset.name
   Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile $download
   if($asset.digest -match '^sha256:([0-9a-fA-F]{64})$'){
    $expected=$Matches[1]
    if((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne $expected){throw 'Verificacao SHA256 do instalador falhou.'}
   }
   if($asset.name -like '*.zip'){
    Expand-Archive -LiteralPath $download -DestinationPath (Join-Path $temp 'installer')
    $Instalador=(Get-ChildItem -LiteralPath (Join-Path $temp 'installer') -Filter 'alloy-installer-windows-amd64.exe' -Recurse|Select-Object -First 1).FullName
   }else{$Instalador=$download}
  }
  if(!$Instalador -or !(Test-Path -LiteralPath $Instalador -PathType Leaf)){throw 'Caminho do instalador EXE invalido.'}
  $installed=Start-Process -FilePath $Instalador -ArgumentList '/S' -PassThru -Wait
  if($installed.ExitCode -notin @(0,3010)){throw ('Instalador falhou. Codigo: '+$installed.ExitCode)}
  $service=Get-Service -Name Alloy -ErrorAction Stop
  Stop-Service -Name Alloy -ErrorAction Stop
 }
 $binary=Join-Path $directory 'alloy-windows-amd64.exe'
 if(!(Test-Path -LiteralPath $binary)){
  $binary=Join-Path (Split-Path $directory -Parent) 'Alloy\alloy.exe'
  if(!(Test-Path -LiteralPath $binary)){throw 'Binario Alloy nao localizado na pasta padrao. Configure manualmente conforme LEIA-ME.txt.'}
 }
 Write-Host ('Destino Dunker Monitor: '+$metadata.monitor_url)
 $secure=Read-Host 'Senha de ingestao (system.ingest_password do credentials.json da central)' -AsSecureString
 $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
 try{$ingestPassword=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)}
 if([string]::IsNullOrWhiteSpace($ingestPassword) -or $ingestPassword.Contains("`n") -or $ingestPassword.Contains("`r")){throw 'Senha de ingestao vazia ou invalida.'}
 $env:DNK_INGEST_PASSWORD=$ingestPassword
 & $binary validate $source
 if($LASTEXITCODE -ne 0){throw 'Configuracao Alloy invalida; a configuracao anterior foi preservada.'}
 [IO.Directory]::CreateDirectory((Join-Path $env:ProgramData 'DunkerMonitor'))|Out-Null
 Stop-Service -Name Alloy -ErrorAction Stop
 $changed=$true
 Copy-Item -LiteralPath $source -Destination $target -Force
 if(!(Test-Path -LiteralPath $regPath)){New-Item -Path $regPath -Force|Out-Null}
 $environment=@($oldEnvironment|Where-Object{$_ -and $_ -notlike 'DNK_INGEST_PASSWORD=*'})+@('DNK_INGEST_PASSWORD='+$ingestPassword)
 New-ItemProperty -Path $regPath -Name Environment -PropertyType MultiString -Value $environment -Force|Out-Null
 $arguments=@('run',$target,('--storage.path='+ (Join-Path $env:ProgramData 'GrafanaLabs\Alloy\data')))
 New-ItemProperty -Path $regPath -Name Arguments -PropertyType MultiString -Value $arguments -Force|Out-Null
 Start-Service -Name Alloy -ErrorAction Stop
 (Get-Service -Name Alloy).WaitForStatus('Running',[TimeSpan]::FromSeconds(30))
 Write-Host ('Alloy iniciado com a configuracao de '+$metadata.instance+'. Backup: '+$backup)
 Write-Host 'Aguarde as primeiras coletas e confira o servidor no Grafana.'
}catch{
 if($changed){
  Stop-Service -Name Alloy -ErrorAction SilentlyContinue
  if($hadConfig){Copy-Item -LiteralPath (Join-Path $backup 'config.alloy') -Destination $target -Force}
  elseif(Test-Path -LiteralPath $target){Remove-Item -LiteralPath $target -Force}
  if($oldRegistry){
   if($oldRegistry.PSObject.Properties.Name -contains 'Arguments'){New-ItemProperty -Path $regPath -Name Arguments -PropertyType MultiString -Value $oldArguments -Force|Out-Null}else{Remove-ItemProperty -Path $regPath -Name Arguments -ErrorAction SilentlyContinue}
   if($oldRegistry.PSObject.Properties.Name -contains 'Environment'){New-ItemProperty -Path $regPath -Name Environment -PropertyType MultiString -Value $oldEnvironment -Force|Out-Null}else{Remove-ItemProperty -Path $regPath -Name Environment -ErrorAction SilentlyContinue}
  }
  if($wasRunning){Start-Service -Name Alloy -ErrorAction SilentlyContinue}
 }
 throw
}finally{
 $env:DNK_INGEST_PASSWORD=$previousProcessPassword
 if($secure){$secure.Dispose()};$ingestPassword=$null
 if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force}
}
