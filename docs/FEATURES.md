# Feature and evidence matrix

This matrix distinguishes local implementation from production readiness. Demo policy choices are not approved organizational policy.

| Capability | Local slice | Remaining gap |
|---|---|---|
| My Studies and study overview | Synthetic study membership filters | Real identity integration |
| Documentation and document history | Append-only text records with version labels | Stable document families, acceptance workflow, binary attachments |
| Discussions | Parent-linked replies, exact document evidence reference | Moderation and attachment quarantine |
| Tasks and decisions | Attributable typed records and evidence links | Dedicated task status/assignment and decision supersession workflows |
| Lifecycle | Active/Paused/Closed and reopening, retained history | Approved role/state matrix; demo permits members to transition |
| Brainstorming | Keyboard-accessible idea records | Visual board, structured export, full board version model |
| Search/download | Membership check on server; deleted items excluded | Production index and revocation testing |
| Administration | Role and group mappings, effective access, audit | Real SIDs, separation of duties, immutable audit sink |
| Persistence | Single-process atomic JSON replacement, optimistic revisions | SQL Server provider, crash-durability and recovery exercises |
| Import | Separate synthetic reconciliation rehearsal | Live source extraction and application ingestion |
| AI and messaging | Disabled; no network calls | Independent integration authorization and implementation |
| IIS | Publish guidance only | Actual Windows/IIS and domain testing |

Security tests and browser evidence must be read alongside this matrix. Automated checks do not establish production security or Section 508 compliance.

## First-slice local evidence

- .NET 10 build: zero warnings and errors.
- HTTP integration suite: 10 cases covering authorization, CSRF, validation, lifecycle, retries, tombstones and graceful restart.
- Synthetic import suite: 9 cases covering fidelity, quarantine, replay and deltas.
- Actual USWDS 3.14.0 Sass compiled locally with Autoprefixer; no runtime CDN.
- Browser checks cover desktop/mobile, keyboard skip navigation, literal HTML payloads, study/admin boundaries and local-only requests. Automated accessibility findings are limited to the screens and tool rules exercised.

No binary-upload safety, power-loss recovery, real directory revocation, SQL Server, Windows/IIS, screen-reader or compliance acceptance result is claimed.
