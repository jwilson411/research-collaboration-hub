# Local validation record

Second preview milestone, Linux build environment:

- Application build: zero warnings and errors.
- `python3 -m unittest discover -s tests -v`: **35 tests passed**, 28.755 seconds (10 original HTTP, 10 file, 6 task, 9 synthetic import cases).
- SQL adapter protocol harness: **19 checks passed** using a simulated ADO.NET connection, not a real database.
- Explicit SQL initializer: refuses missing connection configuration before attempting a connection.
- `node --check` passed for frontend and browser smoke script.
- Independent browser smoke used the actual local launcher, disposable synthetic state and headless Chromium. Verified task assignee/date/status/evidence/history, concurrent-edit draft preservation, exact file download bytes, versions, quarantine, oversized input feedback, admin isolation, keyboard skip navigation and 390-pixel reflow. No JavaScript errors or external requests were observed.
- Independent code review led to regression coverage for deleted task history and deleted/parent-deleted file metadata. Server-side search also excludes inaccessible or deleted attachment records.

These results establish the local synthetic preview only. Browser screenshots are private delivery artifacts, not committed source. Automated accessibility checks from the earlier preview covered board/admin landmarks; the new browser smoke is not a full accessibility audit. No screen-reader, live SQL Server, Windows/IIS, real directory, malware scanner, crash-recovery, scale or production compliance result is claimed.

Reproduction commands and prerequisites are in README, docs/STORAGE.md and tests/browser-smoke.mjs. HTTP test suites own loopback port 5080 and refuse an occupied port. Stop the preview before running them.
