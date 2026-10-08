# Next implementation steps

## Next useful local milestone

The [requirements evidence matrix](REQUIREMENTS-MATRIX.md) is the basis for prioritization. Import exceptions now have owners, immutable review/disposition history and batch receipts; template definitions and resource pointer replacements retain exact versions; search now filters by study/type and exposes selected metadata. These local capabilities do not complete source inventory, organizational governance or production acceptance.

The next useful application seam is synthetic workspace provisioning with stable study identifiers, idempotent requests, validated group mapping and failure isolation (CAP-10). It must not introduce a membership roster, create directory groups or imply external study approval.

In parallel planning, define source/target write ownership and rehearse migration rollback that protects target edits. Add source-link resolution and evidence that every in-scope source record is accounted for across batches; existing receipts cover submitted batches only (CAP-47–54). Search can extend to agreed owner/date filters and remaining metadata, with exact-link tests for renamed and migrated records (CAP-21, CAP-26–27, CAP-54). Structured milestones and blockers remain a coordination gap (CAP-02).

## Policy-dependent local rehearsals

- Define retention/hold semantics before building disposal; test mutation, import and cleanup paths together (CAP-39).
- Define template review/retirement and resource verification responsibility before extending the local lead-managed catalog and contributor attestations (CAP-03, CAP-08).
- Rehearse migration rollback separately from stopped JSON/blob backup restore (CAP-53).
- Replace the synthetic release demonstration with an approved scanner/result lifecycle, quotas and reviewed orphan accounting only when its policy and execution boundary are available (CAP-22).

## Production gates that remain separate

- Exercise the SQL snapshot adapter against an approved disposable SQL Server: concurrency, failure ambiguity, schema, restart and recovery. It remains a bounded single-row preview adapter; normalize entities before scale claims.
- Implement the approved production identity adapter using stable group SIDs, authoritative membership, tested revocation/outage behavior and explicit IIS registration. Keep Production blocked meanwhile.
- Validate Windows/IIS, application subpaths, persisted Data Protection keys, keyboard and screen-reader journeys, deployment rollback and operational recovery on the approved target.

## Decisions needed from the deploying organization

Confirm the production role and approval matrix, records/retention rules for removed and superseded content, approved malware scanning/release process, and migration-source scope with acceptance criteria. These choices cannot be inferred from a synthetic demonstration. Access to an approved Windows/IIS/domain and disposable SQL environment is also needed for the separate integration gates above.

The repository remains a draft implementation. AI and messaging integrations stay disabled and are independent decisions. No current test establishes production or accessibility compliance.
