param([string]$Projeto=$PSScriptRoot)
$ErrorActionPreference='Stop'
Push-Location -LiteralPath $Projeto
try{
 & docker compose -f compose.separado.yaml stop
 if($LASTEXITCODE -ne 0){throw 'Falha ao parar containers.'}
}finally{Pop-Location}
