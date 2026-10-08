# Next implementation steps

## Next useful local milestone

The [requirements evidence matrix](REQUIREMENTS-MATRIX.md) is the basis for prioritization. The highest-value remaining local gap is import exception ownership and disposition: add assigned owners, an immutable resolution trail, guarded retry, and exportable reconciliation receipts. Acceptance should prove that every synthetic source record has an outcome, quarantined material remains inaccessible until resolved, and repeated resolution cannot duplicate or overwrite protected target work (CAP-47–54).

Next, add resource replacement/reverification history and versioned template definitions without changing existing documents or captures (CAP-03, CAP-08). Search coverage is now explicit and paginated; future work can add agreed metadata filters and migrated-link resolution with denied/deleted-link tests (CAP-21, CAP-26–27, CAP-54). A synthetic idempotent provisioning seam can follow, keeping approval and real membership outside the application (CAP-10).

## Policy-dependent local rehearsals

- Define retention/hold semantics before building disposal; test mutation, import and cleanup paths together (CAP-39).
- Rehearse migration rollback that preserves target-side edits separately from the stopped JSON/blob backup restore (CAP-53).
- Replace the synthetic release demonstration with an approved scanner/result lifecycle, quotas and reviewed orphan accounting only when its policy and execution boundary are available (CAP-22).

## Production gates that remain separate

- Exercise the SQL snapshot adapter against an approved disposable SQL Server: concurrency, failure ambiguity, schema, restart and recovery. It is still a bounded single-row preview adapter; normalize entities before scale claims.
- Implement the approved production identity adapter using stable group SIDs, authoritative membership, tested revocation/outage behavior and explicit IIS registration. Keep Production blocked meanwhile.
- Validate Windows/IIS, application subpaths, persisted Data Protection keys, keyboard and screen-reader journeys, deployment rollback and operational recovery on the approved target.

## Decisions needed from the deploying organization

Confirm the production role and approval matrix, records/retention rules for removed and superseded content, approved malware scanning/release process, and migration-source scope with acceptance criteria. These choices cannot be inferred from a synthetic demonstration. Access to an approved Windows/IIS/domain and disposable SQL environment is also needed for the separate integration gates above.

The repository remains a draft implementation. AI and messaging integrations stay disabled and are independent decisions. No current test establishes production or accessibility compliance.
