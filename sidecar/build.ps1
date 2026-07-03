# Builds the sidecar for Windows and drops sidecar.zip where the orchestrator serves it.
$ErrorActionPreference = 'Stop'
$env:Path = "C:\Program Files\Go\bin;$env:Path"
Push-Location $PSScriptRoot
$env:GOOS = 'windows'; $env:GOARCH = 'amd64'; $env:CGO_ENABLED = '0'
go build -ldflags '-s -w' -o sidecar.exe .
$staticDir = Join-Path $PSScriptRoot '..\orchestrator\static'
New-Item -ItemType Directory -Force $staticDir | Out-Null
Compress-Archive -Path .\sidecar.exe -DestinationPath (Join-Path $staticDir 'sidecar.zip') -Force
Remove-Item .\sidecar.exe
Pop-Location
Write-Host 'Built orchestrator/static/sidecar.zip'
