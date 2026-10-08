# Next implementation steps

1. Exercise the SQL snapshot adapter against an approved disposable SQL Server: schema initialization, concurrent writers, rollback, restart and broken-connection ambiguity. Design normalized tables and transaction boundaries before scale claims.
2. Implement an approved production identity adapter using stable group SIDs, current authoritative membership, tested revocation/outage behavior and explicit IIS registration. Keep the current production startup gate until these are implemented and independently validated.
3. Replace the synthetic release policy with an approved scanner and quarantine job/result lifecycle. Add case ownership, safe release evidence, quotas, orphan accounting and records-policy deletion. Rehearse metadata/blob backup and restoration together.
4. Give text documents stable family IDs and explicit current-protocol designation; add accepted/draft semantics and exact evidence selection for binary file versions.
5. Add superseded decisions, governed task reassignment behavior after membership changes, and configuration concurrency/replay protections. Assignment must never grant access.
6. Connect the synthetic reconciliation rehearsal to transactional application ingestion with rollback and protected target-side writes. No real source extraction or migration is authorized by the demo.
7. Validate Windows/IIS, virtual-directory routing, keyboard and screen-reader journeys, restore behavior and deployment rollback on the actual approved target before any production readiness claim.

The repository remains a draft implementation. Optional AI and messaging integrations stay disabled and are independent decisions.
