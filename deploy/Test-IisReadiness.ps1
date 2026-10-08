[CmdletBinding()]
param([Parameter(Mandatory)][string]$SiteName, [Parameter(Mandatory)][string]$AppPoolName)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Readiness inspection requires Windows; Linux cannot validate IIS.' }
Import-Module WebAdministration -ErrorAction Stop
$checks = [Collections.Generic.List[object]]::new()
function Add-Check([string]$Name, [bool]$Passed, [string]$Detail) {
    $checks.Add([pscustomobject]@{ Check = $Name; Passed = $Passed; Detail = $Detail })
}
$pool = Get-Item "IIS:\AppPools\$AppPoolName" -ErrorAction Stop
$site = Get-Item "IIS:\Sites\$SiteName" -ErrorAction Stop
Add-Check 'Dedicated pool assignment' ($site.applicationPool -eq $AppPoolName) 'Also verify no other application shares this pool.'
Add-Check 'No managed runtime' ($pool.managedRuntimeVersion -eq '') 'ASP.NET Core uses its own runtime.'
Add-Check '64-bit pool' (-not $pool.enable32BitAppOnWin64) 'Publish template targets win-x64.'
$windows = Get-WebConfigurationProperty -PSPath 'MACHINE/WEBROOT/APPHOST' -Location $SiteName -Filter 'system.webServer/security/authentication/windowsAuthentication' -Name enabled
$anonymous = Get-WebConfigurationProperty -PSPath 'MACHINE/WEBROOT/APPHOST' -Location $SiteName -Filter 'system.webServer/security/authentication/anonymousAuthentication' -Name enabled
Add-Check 'Windows authentication' ([bool]$windows.Value) 'Inspect actual effective IIS configuration.'
Add-Check 'Anonymous disabled' (-not [bool]$anonymous.Value) 'Application endpoints require authenticated identities.'
$module = @(Get-WebGlobalModule | Where-Object Name -eq 'AspNetCoreModuleV2')
Add-Check 'ASP.NET Core Module' ($module.Count -gt 0) 'Install/repair the matching Hosting Bundle after IIS installation.'
$runtimes = & dotnet --list-runtimes
Add-Check '.NET 10 ASP.NET runtime' ([bool]($runtimes -match '^Microsoft.AspNetCore.App 10\.')) 'Validate current servicing patch separately.'
$checks | Format-Table -AutoSize
Write-Output 'Read-only inspection. Identity mapping, revocation, keys, SQL, restoration, subpaths, and accessibility require separate tests.'
Write-Output 'Current app deliberately rejects Production startup; passing infrastructure checks is not application readiness.'
if (@($checks | Where-Object { -not $_.Passed }).Count -gt 0) { exit 1 }
