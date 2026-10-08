# Next implementation steps

## Next useful local milestone

Give text documents stable family IDs independent of their titles, explicit draft/accepted workspace states, and a fixed handoff snapshot that records exact item/file versions and unresolved actions. Current text version labels still derive from matching titles in Program.cs; binary families and explicit protocol selection already use stable exact IDs. Add superseded decisions so correcting guidance preserves a clear prior record.

## Recovery and import follow-up

- Rehearse metadata-and-blob backup/restore together, interrupted apply and rollback with protected target-side edits. Import currently quarantines changed binary source versions rather than overwrite exact evidence IDs; new source version IDs are required.
- Add reviewed quarantine case ownership/disposition and exportable reconciliation receipts. The connected synthetic importer is not a real source extractor or approved production migration process.
- Replace the synthetic file release policy with an approved scanner/result lifecycle, quotas, reviewed orphan accounting and records-policy disposal. Keep inaccessible orphan bytes isolated until a retention decision exists.

## Production gates that remain separate

- Exercise the SQL snapshot adapter against an approved disposable SQL Server: concurrency, failure ambiguity, schema, restart and recovery. It is still a bounded single-row preview adapter; normalize entities before scale claims.
- Implement the approved production identity adapter using stable group SIDs, authoritative membership, tested revocation/outage behavior and explicit IIS registration. Keep Production blocked meanwhile.
- Validate Windows/IIS, application subpaths, persisted Data Protection keys, keyboard and screen-reader journeys, deployment rollback and operational recovery on the approved target.

The repository remains a draft implementation. AI and messaging integrations stay disabled and are independent decisions. No current test establishes production or accessibility compliance.
