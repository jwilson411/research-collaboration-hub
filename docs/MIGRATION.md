# Synthetic import into the local study hub

The application now has a connected synthetic import path, alongside the separate offline reconciliation CLI described below. It imports only schema-1 manifests explicitly marked `synthetic: true`. This is a local demonstration, not a production source-system extractor, approved migration, or permission translation tool.

## Preview and apply

Use `fixtures/app-import.json` for Atlas. Sign in as the synthetic application administrator, grant the existing synthetic study member Alex the **application** Administrator role, then switch to Alex. This preserves the separate study-group boundary: the administrator identity has no study access and cannot import. No directory membership is edited. The Activity import panel accepts the fixture JSON, displays a read-only preview, then offers explicit apply. To reverse the demo role assignment, switch back to the original synthetic administrator.

All three routes require application administrator role **and** current membership in the requested study's mapped group:

- `POST /api/studies/{id}/imports/preview` with `{ "manifest": ... }` returns accounting without changing study metadata or writing blobs.
- `POST /api/studies/{id}/imports/apply` additionally requires `expectedRevision` and a GUID `requestId`. It applies accepted records and persists the complete outcome report. **Apply permits partial acceptance:** quarantined records are excluded; inspect every outcome.
- `GET /api/studies/{id}/imports` returns prior reports, with IDs, statuses, reasons and counts rather than source bodies or binary data.

Both POST routes use the normal session antiforgery token. Apply requires an active study. Repeated identical apply with the same request ID returns its stored report; reusing the ID with different content conflicts. A new batch can produce unchanged/stale outcomes and still creates a report and attributable audit event. Omission from a batch never deletes data.

## Connected representation and safeguards

The fixture creates four item records (document-family documentation, discussion, reply, decision) and three immutable files (two protocol versions, one reply attachment). Source version records are **files only**, avoiding alternate text-download paths around release checks. File versions retain their source family, numeric `version_number`, supplied `version_label`, author, timestamp and byte checksum. Discussion/decision file evidence uses exact file IDs; all source reference targets remain in provenance. Historical former authors are attribution only and cannot sign in.

Every source outcome is imported, unchanged, stale-ignored, deleted, or quarantined. The envelope is limited to 100 records and 900,000 UTF-8 JSON bytes, beneath the app's 1 MiB request limit. Records are bounded separately; files use the shared filename, extension/signature, UTF-8, 512 KiB, hashing and synthetic-release policy. Unreleased binary records and dependent records quarantine **before content writes**. The source mapping and approved catalog must match the requested study's actual group; a manifest cannot grant access. Individual ACL grants and unresolved authors/groups quarantine.

A persisted per-study ledger holds source revision, fingerprints, exact target IDs, historical metadata and earlier nonbinary source revisions. Higher source revisions update eligible nonbinary records only when their target fingerprint still matches. Existing decision rationale is immutable: supply a distinct source record or use typed decision supersession; an in-place source update quarantines. Source revision and displayed document version are distinct fields. Local target changes or deletions quarantine subsequent imports. Binary version mutation is deliberately unsupported: supply a new source version ID with a distinct numeric family version. Reusing a family version number quarantines, including previously deleted versions.

Explicit higher-revision tombstones retain the ledger but redact publicly returned item body, task, file links and provenance. They never resurrect on retry or later source revision. Parent removal quarantines unless every live structural child has an accepted tombstone in the same batch; child quarantine propagates to the parent. Evidence references to removed content remain historical and unavailable. A source change/deletion of the currently designated protocol quarantines until its designation is explicitly cleared or changed. Imported material never silently changes the current protocol selection.

Metadata, reports, ledger changes and request accounting commit through one `IStudyStore.Change` operation. Blob writes occur before metadata commit to immutable generated names outside the app root. A crash can leave inaccessible orphan bytes; retry accepts only identical regular-file bytes and never overwrites corrupt or symlinked content. Atomic pending-file publication prevents incomplete files becoming valid final blobs. This is metadata transactionality with recoverable orphans, **not** a distributed database/filesystem transaction. Orphan cleanup and records retention need separate approved policies.

```sh
# Owns loopback port 5080; stop the preview first.
DOTNET=/path/to/dotnet python3 tests/test_ingestion.py
```

These tests exercise real local HTTP requests with synthetic state, including access/CSRF, preview purity, source fidelity, restart/replay, malformed types, checksums/ACLs, relationships, duplicate versions, destination conflicts, tombstones, protocol protection, file-release blocking and interrupted-orphan recovery. They do not establish production identity, source completeness, malware protection, SQL Server behavior, records disposition or migration acceptance.

## Separate offline migration rehearsal

`tools/reconcile_import.py` is an offline Python standard-library rehearsal. It is **not connected to application ingestion**, a source extractor, or a production migration system. Its JSON state cannot be loaded into the application. Run it only with synthetic records. It performs no network requests, directory writes, authentication changes, or file extraction.

From the repository root:

```sh
# Default dry-run: complete reconciliation report, no state writes.
python3 tools/reconcile_import.py fixtures/synthetic-import.json
# Persist accepted synthetic records to a separate rehearsal state.
python3 tools/reconcile_import.py fixtures/synthetic-import.json --state /tmp/hub-import-state.json --report /tmp/hub-import-report.json --apply
# Retry: seven unchanged records and identical stored state.
python3 tools/reconcile_import.py fixtures/synthetic-import.json --state /tmp/hub-import-state.json --apply
python3 -m unittest discover -s tests -p test_import.py -v
```

Exit codes: `0` accounted without quarantine; `1` quarantined records; `2` malformed batch or I/O error. `--apply` persists accepted records even if others quarantine. State writes use a flushed temporary file and atomic replacement. Concurrent writers are unsupported. Report output is a separate write: retry the same batch after interruption to regenerate accounting. State existence alone does not prove completion.

## Contract and fidelity

The fixture is the schema example. Each record has a stable `source_id`, immutable study and kind, positive integer source revision, historical author, original timestamp, and explicit ACL. A batch has at most one revision per source ID. Document versions have separate stable IDs; source revision is not the document version label.

| Concern | Rehearsal behavior |
| --- | --- |
| Versions and attachments | Preserve Base64 bytes and require matching SHA-256; never unpack or execute content |
| Metadata | Preserve supplied record verbatim, including timestamp, author, version label, source URL, and additional metadata |
| Conversation structure | Validate parent kinds; reject cycles, missing/quarantined targets, and cross-study relationships |
| Exact evidence | References target stable version/reply IDs |
| Access mappings | Require approved synthetic group mapping and exact group-only ACL; unresolved mappings and individual grants quarantine |
| Historical identities | Catalog entry is required for attribution; inactive former members remain authors; no entry creates entitlement |
| Repeatability | Canonical fingerprints and state hash; input order does not change outcomes |
| Updates | Higher source revisions replace earlier representations; same-revision conflicts quarantine; older revisions are ignored |
| Deletions | Explicit tombstones preserve attribution and block resurrection, including later revisions |
| Accounting | Every input receives imported, deleted, unchanged, stale-ignored, or quarantined outcome with reasons |
| Deleted targets | Historical references remain recorded and reported as unavailable |

Omission from a batch does not delete a record. Recreated source objects need new stable IDs. Quarantined records remain in the original input; reports preserve IDs, fingerprints, and reasons. Retain manifests alongside reports. There is no quarantine case assignment, disposition approval, or repair UI.

## Production gaps

There is no source extraction, real directory verification, nested-group or item-ACL translation, malware release pipeline, legal hold enforcement, legacy redirects, signed evidence, scale benchmark, wave orchestration, or target-write rollback. Metadata is preserved, not verified against authoritative systems. Caller-supplied mapping catalogs establish neither directory authority nor app access.

Production requires approved inventory and field maps, verified directory mappings, quarantined binary storage, durable item outcomes and case ownership, revocation and negative authorization tests, interrupted-batch recovery, transactional application ingestion, cutover write ownership, and restore/rollback rehearsals. Counts alone prove neither source completeness nor migration acceptance.

## Operator exception review and reconciliation receipts

An application Administrator who is also a current member of the study can open its import exception queue. Quarantined and stale outcomes are tracked separately for each applied batch. Assign a current study member, record a review note, then explicitly resolve tracking as **Excluded** or **Corrected in a later import**. Reopen a resolved case to record further work. Assignment grants no access. Review never changes the automatic outcome, imports data, releases files, creates a principal, or overrides group/ACL quarantine.

A corrected disposition must cite a later applied batch in the same destination study with the same source study, source record ID and kind, an equal or newer source revision, and an automatic imported/unchanged/deleted outcome. A different record with the same local ID is insufficient. Original batch outcomes remain unchanged. Older reports without source lineage cannot support a corrected disposition; an explicit exclusion remains available.

Capture a receipt to preserve the applied report and the exception owners, dispositions and immutable actor/time/note history **as of capture**. JSON receipt downloads contain metadata and outcome reasons, never source bodies or binary content. Subsequent reviews produce new history and new receipts; they do not rewrite earlier receipts. A receipt covers only its submitted synthetic batch. It does not prove full source inventory, external migration completeness, current target availability, formal acceptance or approval. Deleted target IDs may remain historical identifiers; normal content/download authorization still applies.

New reports have SHA-256 integrity digests, review events form a digest chain, and each receipt has its own digest. Reads, export and replay validate the retained evidence and fail closed on detected corruption. These are local corruption checks, not digital signatures or protection against someone able to rewrite the whole database and recompute every digest. Legacy reports created before this feature have no original digest; structural validation and their first review/receipt establish a baseline, not retrospective authenticity. Notes must contain synthetic information only.

Writes use the study revision and a request identifier, require an active study, and check current administrator permission and group membership before retry handling. A successful retry does not append history or capture a second receipt. Reopening a study permits new review work while preserving the historical batch and receipt records.
