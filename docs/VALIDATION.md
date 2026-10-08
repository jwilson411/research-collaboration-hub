# Local validation record

Third preview milestone, Linux build environment:

- Application build: zero warnings and errors.
- `python3 -m unittest discover -s tests -v`: **57 tests passed**, 56.470 seconds (10 core HTTP, 12 file, 3 configuration, 9 offline import, 12 connected ingestion, 5 protocol and 6 task cases).
- SQL adapter protocol harness: **19 checks passed** using a simulated ADO.NET connection, not a real database.
- Explicit SQL initializer: refuses missing connection configuration before attempting a connection.
- `node --check` passed for frontend and browser smoke script.
- Independent browser smoke used the actual local launcher, disposable synthetic state and headless Chromium. Verified task assignee/date/status/evidence/history, concurrent-edit draft preservation, exact file download bytes, versions, quarantine, oversized input feedback, admin isolation, keyboard skip navigation and 390-pixel reflow. No JavaScript errors or external requests were observed.
- Third-milestone browser checks additionally verified explicit protocol v1 remaining selected after v2 upload, exact task/decision file citations, stale administrator edits, and administrator roles granting no extra study membership. Connected import produced 7 imported records, then 7 unchanged on repeat; historical versions, original author/date, nested reply, attachment bytes and study isolation passed.
- Independent adversarial review produced regression coverage for quarantined binary content, malformed manifests, interrupted immutable blob retries, unavailable evidence and protection of imported parents with live native or imported children. Server-side search excludes inaccessible or deleted attachment records.

These results establish the local synthetic preview only. Browser screenshots are private delivery artifacts, not committed source. Automated accessibility checks from the earlier preview covered board/admin landmarks; the new browser smoke is not a full accessibility audit. No screen-reader, live SQL Server, Windows/IIS, real directory, malware scanner, crash-recovery, scale or production compliance result is claimed.

Reproduction commands and prerequisites are in README, docs/STORAGE.md and tests/browser-smoke.mjs. HTTP test suites own loopback port 5080 and refuse an occupied port. Stop the preview before running them.
