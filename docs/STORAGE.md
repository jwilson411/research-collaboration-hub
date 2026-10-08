# Storage providers and SQL rehearsal

`IStudyStore` separates application operations from persistence. `Json` is the default local demo provider. `SqlServer` selects `SqlStudyStore`; an unknown provider or missing `HUB_SQL_CONNECTION` fails closed. Production startup is still blocked until the production identity path is implemented and validated.

The SQL adapter is a **bounded preview adapter**, not a scalable normalized research repository. It stores one JSON snapshot in `dbo.HubSnapshot`, capped at 8 MiB of UTF-8 JSON. Every write serializes all studies and takes a serializable transaction with `UPDLOCK, HOLDLOCK`; the conditional update checks the original snapshot revision. Application optimistic study revisions and request fingerprints are evaluated within that transaction. Only explicit HTTP 2xx operation results commit. Failed results, callback exceptions, and revision conflicts do not commit. Each read deserializes a fresh object graph.

There is no automatic DDL, startup seeding, connection fallback, or operation retry. A failed commit can have an ambiguous outcome; reuse the original application request ID after operator verification, rather than inventing a fresh operation. Existing application idempotency applies only to endpoints that implement request IDs. This adapter does not make every endpoint idempotent.

## Explicit setup in an approved local SQL test environment

1. Provision a dedicated test database using existing approved administration procedures; no script here creates databases, credentials, logins, or grants.
2. Review and execute `deploy/001-snapshot.sql` in that database. It creates a singleton schema-versioned row with **empty studies, roles, and audit**. Re-running the script refuses to overwrite the table.
3. Grant the existing runtime identity only the required `SELECT` and `UPDATE` permissions on `dbo.HubSnapshot` through the approved administration process. DDL rights belong to a separate setup identity. No permission changes have been executed by this project.
4. Supply `HUB_SQL_CONNECTION` through protected process configuration. Never put connection strings in tracked files, command history, screenshots, or logs. A named database, encryption, server certificate validation, no attached files, and no persisted security information are required. Prefer integrated authentication with the intended service identity when validated. No certificate-validation bypass is provided.
5. Set `HUB_STORAGE_PROVIDER=SqlServer`. For the current synthetic loopback application, retain `ASPNETCORE_ENVIRONMENT=Development` and `HUB_DEMO_ENABLED=true`.
6. If synthetic content is wanted, invoke the application once with `--initialize-synthetic-sql`. This is a separate command-line action, requires Development plus explicit demo enablement, and refuses any snapshot except untouched revision zero with empty collections. It is never executed automatically by app startup and is not an HTTP endpoint.

An empty SQL database intentionally has no application administrator. SQL initialization does not configure real directory identities or real membership. The synthetic seed is the same clearly labeled fixture used by the local JSON preview. The independent manifest CLI in `docs/MIGRATION.md` is not an app ingestion path.

## Verification and limits

Run adapter protocol checks using:

```sh
dotnet run --project deploy/protocol-tests/StorageProtocolTests.csproj
```

These use a fake ADO.NET connection and minimal domain stand-ins. They verify isolated reads, rollback on failed results/exceptions, transaction isolation and SQL command shape, parameterization, optimistic update failure, snapshot bounds, seed guards, and connection safeguards. They **do not prove SQL Server locking, SQL syntax, TLS, identity, pooling, timeout behavior, persistence, or recovery**.

Real SQL tests remain unrun. Docker was present in the Linux build environment but daemon access was denied; `sqlcmd` was unavailable. No permissions were expanded and no SQL service was started. Before promotion, exercise concurrent requests from separate processes, same-key retries after connection loss, SQL restart, backup/restore, corruption/schema rejection, least privilege, TLS validation, and directory-authorized end-to-end operations against actual SQL Server. Normalize entities and binary storage before capacity claims; whole-state serialization and global write locking are explicit limitations.

## Dependency basis

The project pins Microsoft.Data.SqlClient **6.1.7**. Microsoft's [driver support lifecycle](https://learn.microsoft.com/en-us/sql/connect/ado-net/sqlclient-driver-support-lifecycle) lists the 6.1 LTS line through August 14, 2028 and identifies 6.1.7 as its current patch. The [official package page](https://www.nuget.org/packages/Microsoft.Data.SqlClient/6.1.7) lists .NET 8+ compatibility. Recheck current servicing and vulnerability advisories before an approved deployment. Sources checked October 8, 2026.
