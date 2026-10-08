# Windows/IIS implementation gate — untested

The target architecture is ASP.NET Core 10 behind the ASP.NET Core Module in a dedicated IIS application pool, with SQL Server and authoritative existing directory groups. **This Linux demo deliberately refuses Production startup. Publishing files does not remove that gate.**

.NET 10 is LTS, supported through November 14, 2028. Verify current servicing patches before use: https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core .

## Build/publish rehearsal

On a Windows development machine with .NET 10 and Node LTS:

```powershell
npm ci
npm run build
dotnet build
dotnet publish -c Release -o artifacts/publish
```

The Web SDK generates `web.config` for IIS. No IIS deployment or network binding is performed by these commands. Local demo execution uses the README environment settings and loopback only.

## Required implementation before an IIS run

- Implement a production identity adapter using the organization-approved Windows authentication path. Configure deployed IIS authentication and `web.config`; launchSettings is insufficient. Disable anonymous authentication for application endpoints. Never trust browser-provided identity headers.
- Resolve authoritative, stable directory group SIDs with explicit freshness, nested-group, outage and revocation policy. No application membership roster or admin-content bypass. Explicitly register any claims transformation needed in IIS; do not assume it runs automatically.
- Replace `IStudyStore` with a transactional SQL Server provider, schema migrations, concurrency tokens and durable unique idempotency keys. Validate constraints, rollback, backup/restore, outage handling and production capacity. The JSON store only supports one process.
- Persist and protect Data Protection keys under a dedicated app pool identity. Install the matching supported Hosting Bundle after IIS. Configure least-privilege filesystem/database access and HTTPS.
- Implement approved attachment storage outside static/application roots, file signatures and extension allowlist, quotas, malware quarantine, and authorized streaming downloads. Align Kestrel and IIS limits. This slice accepts text documents only.
- Validate virtual-directory base paths, Windows/domain integration, directory revocation, authentication challenges, anti-forgery, recovery, access auditing and accessibility on actual Windows/IIS. Root-path Linux tests establish none of these.

References: https://learn.microsoft.com/en-us/aspnet/core/host-and-deploy/iis/?view=aspnetcore-10.0 and https://learn.microsoft.com/en-us/aspnet/core/security/authentication/windowsauth?view=aspnetcore-10.0 .
