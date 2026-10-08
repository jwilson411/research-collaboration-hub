# Windows/IIS deployment rehearsal — execution untested

The intended target is ASP.NET Core 10 in a dedicated IIS application pool, with on-premises SQL Server and existing authoritative directory groups. **The current application intentionally refuses Production startup. The deployment pack prepares build artifacts and checks infrastructure; it does not remove that gate or establish production readiness.** Linux preview evidence cannot validate Windows authentication, IIS, domain policy, SQL Server, or accessibility conformance.

.NET 10 is LTS through November 14, 2028 according to Microsoft's [support policy](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core). Use current servicing patches and a supported Windows Server version.

## Build artifacts only

On a Windows build workstation with .NET 10 SDK and a supported Node.js version:

```powershell
./deploy/Publish-Preview.ps1 -OutputDirectory ./artifacts/iis-review
```

This restores dependencies, compiles actual local USWDS assets, publishes framework-dependent `win-x64` files, and places the reviewed template at `web.config`. It creates no IIS site, application pool, binding, certificate, database, or network listener. Output must be a new directory to avoid stale mixed artifacts. This PowerShell script has not been executed on Windows here.

`deploy/web.config.template` specifies in-process ASP.NET Core Module hosting, Production environment, Windows authentication enabled, anonymous authentication disabled, and a 1 MiB IIS request cap matching the app's current cap. It contains no credential, official-government identifier, or demo enablement. Authentication sections may be locked by server policy: an authorized administrator must review effective configuration; do not unlock server-wide sections indiscriminately. IIS launch settings alone do not configure deployed authentication.

## Future approved host preparation

- Install IIS and its Windows Authentication feature, then the matching ASP.NET Core Hosting Bundle. If IIS was installed later, repair the bundle. Use a dedicated 64-bit application pool with **No Managed Code**, a least-privilege service identity, and no unrelated applications.
- Configure the approved HTTPS binding and certificate; no hosting/binding operation is included or authorized by this rehearsal. Current preview remains loopback-only. Do not expose Development mode to LAN or public interfaces.
- Give the app pool read access to published files. Keep uploads, persisted keys, database configuration, and operational logs outside the published/static roots, with narrowly scoped ACLs. Configure persisted Data Protection keys and protect them using the approved Windows mechanism. Validate key continuity across recycle and restore; this is not implemented by the template.
- Implement the production Windows principal adapter and authoritative stable group-SID resolution with explicit nested-group, freshness, outage, and revocation policy. No browser identity header or application membership roster may replace directory authority. Any `IClaimsTransformation` use must be explicitly registered and exercised under IIS; it does not run automatically merely because Windows authentication is enabled.
- Initialize the SQL schema deliberately using [STORAGE.md](STORAGE.md). Supply `HUB_SQL_CONNECTION` via protected process configuration and do not write it into the template or repository. Do not seed production data or enable demo/reset options.
- Implement and validate resource authorization across direct URLs, search, attachments, downloads, boards, and administration. Keep antiforgery validation on every mutation. Complete file quarantine/scanning, recovery, audit, and records-policy work before accepting real data.

## Read-only infrastructure inspection

On the intended Windows test host, after its owner has separately configured a test site:

```powershell
./deploy/Test-IisReadiness.ps1 -SiteName 'ResearchHubTest' -AppPoolName 'ResearchHubTestPool'
```

The script reads effective site authentication, app pool assignment/architecture/runtime mode, the ASP.NET Core module, and installed ASP.NET Core 10 runtime. It does not change configuration and does not read connection strings. It checks the named site root; applications hosted under a subpath require additional effective-configuration inspection. No Windows/PowerShell execution has been performed here.

A future approved IIS validation must cover: actual authenticated principal/group SIDs; removed-member sessions and search/download access; direct-object negatives; CSRF; app pool recycle and Data Protection continuity; SQL concurrency/restart/restore; HTTPS; request limits; application subpaths and local asset URLs; keyboard/mobile navigation and assistive technology; configuration rollback. Keep the previous published artifact and a compatible verified database backup; database rollback and reconciliation of post-release writes require a rehearsed plan, not merely copying older binaries. Passing the read-only checks does not unlock Production.

## Primary references

- [Microsoft: IIS hosting](https://learn.microsoft.com/en-us/aspnet/core/host-and-deploy/iis/?view=aspnetcore-10.0)
- [Microsoft: Windows authentication](https://learn.microsoft.com/en-us/aspnet/core/security/authentication/windowsauth?view=aspnetcore-10.0)
- [Microsoft: Data Protection configuration](https://learn.microsoft.com/en-us/aspnet/core/security/data-protection/configuration/overview?view=aspnetcore-10.0)

Sources checked October 8, 2026. These instructions express required implementation and verification work, not a tested deployment or approval claim.
