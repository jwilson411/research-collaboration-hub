# Research collaboration hub

A local, synthetic research-study collaboration preview built with ASP.NET Core 10 and the U.S. Web Design System. It is not an official government service. No actual research or patient data belongs in this demo.

## Local quick start

Check out `feature/local-study-hub` for this draft implementation. Install a supported .NET 10 SDK and Node.js LTS. From this directory:

```sh
npm ci
npm run build
HUB_DEMO_ENABLED=true ASPNETCORE_ENVIRONMENT=Development dotnet run
```

Open http://127.0.0.1:5080 **on the development computer**. This loopback address does not open the computer's preview from a phone. No LAN listener, tunnel, public hosting, paid CI, AI requests, or messaging integration is provided.

PowerShell equivalent:

```powershell
$env:HUB_DEMO_ENABLED = 'true'
$env:ASPNETCORE_ENVIRONMENT = 'Development'
dotnet run
```

The demo requires both explicit enablement and Development. It refuses other startup modes, verifies the remote address and Host, and binds only loopback. Synthetic identities can be selected by any local visitor: this is a demonstration mechanism, not real authentication. Alex has Atlas access, Sam has Beacon access, and Morgan administers mappings and application roles without an automatic study-content bypass. Group membership is an immutable synthetic fixture, not an editable roster.

Data persists to `.data/hub.json`; set `HUB_DATA` to an alternate local file for isolated tests. Back up while stopped. The single-process JSON provider uses atomic replacement and an `IStudyStore` boundary. It is not a SQL Server provider, distributed database, or production durability guarantee.

## Walkthrough

1. Open My Studies as Alex. Review Atlas's protocol, orientation and open question.
2. Create a documentation revision, discussion reply, decision, next action or idea. Refresh to see persisted changes.
3. Open Sam's session. Atlas URLs, search hits and downloads are unavailable. Reopen Beacon and continue its historical record.
4. Select Morgan. Inspect application roles, directory-group mappings, effective access and audit. Admin privileges alone do not disclose study content.
5. Submit stale changes from two tabs: the second request must be rejected rather than silently overwrite work.

See [feature matrix](docs/FEATURES.md), [IIS implementation gate](docs/IIS.md), and [synthetic migration rehearsal](docs/MIGRATION.md). This preview is not production-ready or an accessibility compliance certification.

## Validation

```sh
dotnet build
python3 -m unittest discover -s tests -v
```

Tests that launch the application require `dotnet` on PATH (or set `DOTNET` to its executable). Stop the preview first: the HTTP suite owns loopback port 5080. No hosted CI is configured.
