param([string]$Projeto=$PSScriptRoot)
$ErrorActionPreference='Stop'
Push-Location -LiteralPath $Projeto
try{
 & docker compose -f compose.separado.yaml up -d --no-build
 if($LASTEXITCODE -ne 0){throw 'Falha ao iniciar containers. Confira os logs.'}
}finally{Pop-Location}
