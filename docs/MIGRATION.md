# Synthetic migration rehearsal

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
