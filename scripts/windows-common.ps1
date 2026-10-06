$ErrorActionPreference='Stop'
function Normalize-DockerPath([string]$Path){
 if([string]::IsNullOrWhiteSpace($Path)){return ''}
 $value=$Path.Replace('\','/').TrimEnd('/').ToLowerInvariant()
 $value=[regex]::Replace($value,'^/(?:run/desktop/mnt/host|host_mnt|mnt)/([a-z])/', '$1:/')
 return $value
}
function Get-DunkerInventory([string]$Root){
 $list=New-Object System.Collections.Generic.List[object]
 $ids=@(& docker ps -aq --filter 'label=com.docker.compose.project')
 if($LASTEXITCODE -ne 0){throw 'Nao foi possivel consultar containers Docker.'}
 $format='{{json .}}'
 foreach($id in $ids){
  if(!$id){continue}
  $raw=& docker inspect --format $format $id
  if($LASTEXITCODE -ne 0){continue}
  $item=($raw -join "`n")|ConvertFrom-Json
  $labels=$item.Config.Labels;$project=$labels.'com.docker.compose.project';$working=$labels.'com.docker.compose.project.working_dir'
  if($project -notlike '*dunker*' -and (Normalize-DockerPath $working) -ne (Normalize-DockerPath $Root)){continue}
  $list.Add([pscustomobject]@{Name=$item.Name.TrimStart('/');Image=$item.Config.Image;Status=$item.State.Status;Health=$item.State.Health.Status;Project=$project;Service=$labels.'com.docker.compose.service';WorkingDirectory=$working;ComposeFiles=$labels.'com.docker.compose.project.config_files';Mounts=@($item.Mounts|ForEach-Object{[pscustomobject]@{Type=$_.Type;Source=$_.Source;Destination=$_.Destination;VolumeName=$_.Name;ReadWrite=$_.RW}});Ports=$item.NetworkSettings.Ports})
 }
 return $list.ToArray()
}
function Write-DockerReport([string]$Report,[string]$Stage,[object[]]$Items){
 $utf8=New-Object System.Text.UTF8Encoding($false)
 [IO.Directory]::CreateDirectory($Report)|Out-Null
 $json=ConvertTo-Json -InputObject @($Items) -Depth 8
 [IO.File]::WriteAllText((Join-Path $Report ('docker-'+$Stage+'.json')),$json,$utf8)
 $text="DUNKER MONITOR - DOCKER $Stage`r`n"+($Items|Select-Object Name,Image,Status,Health,Project,Service,WorkingDirectory|Format-List|Out-String)
 [IO.File]::WriteAllText((Join-Path $Report ('docker-'+$Stage+'.txt')),$text,$utf8)
}
