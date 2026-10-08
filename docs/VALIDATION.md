# Local validation record

Fifth preview milestone, Linux build environment:

- Application build: zero warnings and errors.
- `python3 -m unittest discover -s tests -v`: **107 tests passed**, 112.722 seconds (10 core HTTP, 12 file, 11 brainstorming, 3 configuration, 3 document workflow, 9 handoff, 9 offline import, 12 connected ingestion, 22 independent security, 5 onboarding, 5 protocol and 6 task cases).
- SQL adapter protocol harness: **19 checks passed** using a simulated ADO.NET connection, not a real database.
- Explicit SQL initializer: refuses missing connection configuration before attempting a connection.
- `node --check` passed for frontend and browser smoke script.
- Independent browser smoke used the actual local launcher, disposable synthetic state and headless Chromium. Verified task assignee/date/status/evidence/history, concurrent-edit draft preservation, exact file download bytes, versions, quarantine, oversized input feedback, admin isolation, keyboard skip navigation and 390-pixel reflow. No JavaScript errors or external requests were observed.
- Prior and current browser checks additionally verified explicit protocol v1 remaining selected after v2 upload, exact task/decision file citations, stale administrator edits, and administrator roles granting no extra study membership. Connected import produced 7 imported records, then 7 unchanged on repeat; historical versions, original author/date, nested reply, attachment bytes and study isolation passed.
- Independent adversarial review produced regression coverage for quarantined binary content, malformed manifests, interrupted immutable blob retries, unavailable evidence and protection of imported parents with live native or imported children. Server-side search excludes inaccessible or deleted attachment records.

- Fourth-milestone browser regression ran from fresh synthetic state through the actual launcher: renamed immutable document family; Researcher/Reviewer/StudyLead transitions; keyboard inspection of seeded capture history; quarantine rejection with preserved inputs followed by explicit-selection retry; unchanged snapshot JSON and visible content after task edits and Closed → Active lifecycle changes. Mobile width 390 had no horizontal overflow; no JavaScript errors or external requests were observed.
- Legacy imported-item serialization omits absent document-version metadata, preserving prior target fingerprints; omission and subsequent source-delta reconciliation are covered by the ingestion suite.
- Independent milestone-four security checks covered privileged request replay, accepted document/file and ancestor retention, review-history removal, snapshot body/name/hash masking, access revocation, missing/tampered evidence, release-policy changes and restart. Independent static review findings were addressed before the final combined run.

- Fifth-milestone independent browser checks passed keyboard ordering with logical focus/live announcements, immutable idea history and decisions from earlier versions, session summaries/downloads, archive/reopen, closed-study rejection with draft retention, and personal orientation persistence/resume/identity isolation. A focused follow-up verified exact historical-version search, repeated same-hash navigation and task evidence links after the navigation correction.
- Axe found **zero violations** on the exercised onboarding and brainstorming-session screens. Mobile screenshots at 390 pixels were visually reviewed. These checks establish neither full screen-reader acceptance nor accessibility compliance.
- Independent session/onboarding adversarial checks covered role-before-replay, cross-study/session/idea boundaries, complete ordering, deletion/history/export masking, private personal revisions, context changes after imported conversation updates, and restart. Optional board metadata is omitted when absent to preserve existing import fingerprints.

These results establish the local synthetic preview only. Browser screenshots are private delivery artifacts, not committed source. Automated accessibility checks cover only the exercised screens and rules; the browser smoke is not a full accessibility audit. No screen-reader, live SQL Server, Windows/IIS, real directory, malware scanner, crash-recovery, scale or production compliance result is claimed.

Reproduction commands and prerequisites are in README, docs/STORAGE.md and tests/browser-smoke.mjs. HTTP test suites own loopback port 5080 and refuse an occupied port. Stop the preview before running them.
