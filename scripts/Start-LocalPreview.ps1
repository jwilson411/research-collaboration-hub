$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$env:ASPNETCORE_ENVIRONMENT = 'Development'
$env:HUB_DEMO_ENABLED = 'true'
if (-not $env:HUB_DEMO_FILE_RELEASE) { $env:HUB_DEMO_FILE_RELEASE = 'true' }
Write-Output 'Local synthetic preview: http://127.0.0.1:5080 on this computer only.'
Write-Output 'Synthetic release permits plain text and the bundled demo PNG only; other binaries stay quarantined.'
& dotnet run --project (Join-Path $projectRoot 'ResearchHub.csproj') --no-launch-profile
exit $LASTEXITCODE
