param([Parameter(Mandatory=$true)][string]$Projeto)
& (Join-Path $PSScriptRoot 'ATUALIZAR-PROJETO.ps1') -Projeto $Projeto -SomenteVerificar
