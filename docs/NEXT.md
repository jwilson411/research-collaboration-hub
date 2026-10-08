# Next implementation steps

## Next useful local milestone

Add explicit decision supersession: preserve rationale, alternatives, responsible participant, effective date and exact evidence while showing which decision replaced an earlier one. Current generic decision records have attribution and exact evidence, but no governed replacement chain. Keep this a collaboration record, not formal study approval.

Acceptance criteria: a replacement retains the exact earlier decision and source idea/document/file revisions; stale or repeated replacement requests cannot fork or duplicate the chain; superseded decisions remain discoverable with clear status; cross-study and deleted evidence are rejected; handoffs preserve the state at capture; keyboard/mobile flows make the current guidance unambiguous.

After that, prioritize governed document templates and explicit resource pointers with owner/source/last-verified date. The current workspace has reusable seeded guidance but no governed template selection or resource-verification lifecycle. Avoid adding speculative integrations.

## Recovery and import follow-up

- Rehearse metadata-and-blob backup/restore together, interrupted apply and rollback with protected target-side edits. Import currently quarantines changed binary source versions rather than overwrite exact evidence IDs; new source version IDs are required.
- Add reviewed quarantine case ownership/disposition and exportable reconciliation receipts. The connected synthetic importer is not a real source extractor or approved production migration process.
- Replace the synthetic file release policy with an approved scanner/result lifecycle, quotas, reviewed orphan accounting and records-policy disposal. Keep inaccessible orphan bytes isolated until a retention decision exists.

## Production gates that remain separate

- Exercise the SQL snapshot adapter against an approved disposable SQL Server: concurrency, failure ambiguity, schema, restart and recovery. It is still a bounded single-row preview adapter; normalize entities before scale claims.
- Implement the approved production identity adapter using stable group SIDs, authoritative membership, tested revocation/outage behavior and explicit IIS registration. Keep Production blocked meanwhile.
- Validate Windows/IIS, application subpaths, persisted Data Protection keys, keyboard and screen-reader journeys, deployment rollback and operational recovery on the approved target.

## Decisions needed from the deploying organization

Confirm the production role and approval matrix, records/retention rules for removed and superseded content, approved malware scanning/release process, and migration-source scope with acceptance criteria. These choices cannot be inferred from a synthetic demonstration. Access to an approved Windows/IIS/domain and disposable SQL environment is also needed for the separate integration gates above.

The repository remains a draft implementation. AI and messaging integrations stay disabled and are independent decisions. No current test establishes production or accessibility compliance.
