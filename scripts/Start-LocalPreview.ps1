[CmdletBinding()]
param([switch]$ReleaseSyntheticFiles)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$dotnet = (Get-Command dotnet -ErrorAction Stop).Source
$sdks = & $dotnet --list-sdks
if ($LASTEXITCODE -ne 0 -or -not ($sdks | Where-Object { $_ -match '^10\.0\.' })) {
    throw 'Install a currently serviced .NET 10 SDK before starting this preview.'
}
$settings = @{
    ASPNETCORE_ENVIRONMENT = 'Development'
    DOTNET_ENVIRONMENT = 'Development'
    HUB_DEMO_ENABLED = 'true'
    HUB_STORAGE_PROVIDER = 'Json'
    HUB_DEMO_FILE_RELEASE = $ReleaseSyntheticFiles.IsPresent.ToString().ToLowerInvariant()
}
$saved = @{}
foreach ($name in $settings.Keys) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$previewExitCode = 1
Push-Location $projectRoot
try {
    $selectedSdk = & $dotnet --version
    if ($LASTEXITCODE -ne 0 -or $selectedSdk -notmatch '^10\.0\.[0-9]+$') {
        throw 'The selected SDK must be stable .NET 10; check global.json and installed SDKs.'
    }
    foreach ($name in $settings.Keys) { [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process') }
    Write-Output 'Local synthetic JSON preview: http://127.0.0.1:5080 on this computer only. Stop with Ctrl+C.'
    if ($ReleaseSyntheticFiles) { Write-Output 'Synthetic release enabled: validated text and the bundled demo PNG only; other binaries stay quarantined.' }
    else { Write-Output 'All uploads stay quarantined. Use -ReleaseSyntheticFiles for the synthetic file walkthrough.' }
    & $dotnet restore --locked-mode
    if ($LASTEXITCODE -ne 0) { throw 'Locked package restore failed; the preview was not started.' }
    & $dotnet run --project (Join-Path $projectRoot 'ResearchHub.csproj') --no-restore --no-launch-profile
    $previewExitCode = $LASTEXITCODE
}
finally {
    foreach ($name in $settings.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    Pop-Location
}
exit $previewExitCode
