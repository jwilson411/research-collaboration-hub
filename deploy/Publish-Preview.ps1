[CmdletBinding()]
param([string]$OutputDirectory = (Join-Path $PSScriptRoot '../artifacts/iis-publish'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path $output) { throw 'Choose a new empty output directory to avoid mixing old deployment files.' }
Push-Location $root
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Asset build failed.' }
    & dotnet publish ResearchHub.csproj -c Release -r win-x64 --self-contained false -o $output
    if ($LASTEXITCODE -ne 0) { throw 'Publish failed.' }
    Copy-Item (Join-Path $PSScriptRoot 'web.config.template') (Join-Path $output 'web.config')
    Write-Output 'Build output prepared only. No IIS site, bindings, authentication, database, or hosting was changed.'
    Write-Output 'Production startup remains intentionally blocked; review docs/IIS.md before any future deployment.'
} finally { Pop-Location }
