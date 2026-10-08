# Morning preview

This is a local synthetic research collaboration demo. Use the development computer's browser; a phone's localhost cannot reach it. No public/LAN preview, tunnel or production deployment is provided. Start from the published feature branch and follow the README prerequisites.

For the complete file walkthrough, explicitly enable the limited synthetic release policy:

```sh
./scripts/start-demo.sh --release-synthetic-files
```

On Windows, the corresponding command is `./scripts/Start-LocalPreview.ps1 -ReleaseSyntheticFiles`. Windows execution has not been validated here. Both launchers use JSON storage, Development and loopback. The release switch permits validated text and the bundled synthetic PNG only; there is no malware scanner. Omit it to keep all uploads quarantined. Use fresh empty `HUB_DATA` and `HUB_FILES` locations if you need a pristine demo; do not delete existing state to reset it.

## Researcher journey

1. As **Alex**, open Atlas. Inspect the exact current protocol, people, open conversations and next actions. Complete one personal orientation step and revisit it.
2. Open Living documentation and the document library. Inspect native version-history disclosures; create a Draft from an exact template definition. As **Casey**, inspect review states. Workspace acceptance is not formal study approval.
3. Add a synthetic discussion/reply and a small text attachment. Download it and inspect its exact file version. Record a task with an owner, date and evidence, then a decision with rationale and alternatives.
4. Capture a handoff, update the task, then revisit the handoff to compare its fixed context. Open a brainstorming session, add/revise an idea, reorder it with the keyboard and inspect its retained history.
5. In Living documentation, replace or reverify a resource pointer with a reason; inspect its previous owner/source/date. As **Riley**, append a template definition and confirm earlier document provenance remains unchanged.
6. Search for a displayed owner name or task status, narrow by study and record type, and follow an exact result. As **Sam**, confirm Atlas is absent. Open Beacon and inspect historical context before explicitly reopening it.

## Administrator and migration journey

1. As **Morgan**, inspect roles, effective access, mappings and audit. Create a uniquely named synthetic study with an explicitly selected existing group. It starts empty and Paused; Morgan still cannot open its content. No group or membership is created.
2. As an eligible mapped member, open the new study. Its contact is unconfigured, not guessed. Explicitly reopen it before contributing.
3. To exercise import administration in Atlas, Morgan may grant Alex the application Administrator role, then switch to Alex. The role alone grants no study membership. Use only `fixtures/app-import.json` in the Activity manifest editor.
4. Start an **isolated rehearsal**. Inspect each submitted record, version, parent/reference and legacy-link status, mapping validity and quarantine outcomes. Abort and retry; apply the simulated batch, inspect history, then preview `fixtures/app-import-delta-conflict.json` as a delta to see a same-revision source conflict. Roll back the isolated branch. Live study content and attachment bytes remain unchanged; session/audit metadata is persisted. This is not a production migration or operational rollback.
5. Separately preview a real **synthetic demo import** before explicitly applying it. Inspect accepted and quarantined outcomes. Use `fixtures/app-import-exception.json` to produce an unresolved-source exception: assign, review and resolve its tracking state, capture a receipt, then reopen it. Disposition never overrides quarantine or accepts unknown mappings.
6. Use the Activity source-record resolver for an imported source-study/source-record pair. It opens only an authorized exact local target; missing, inaccessible and unavailable records share the same response. External URLs are never fetched or redirected to.
7. Restore Alex's application role if the import demonstration is finished. Review the audit and stop the preview with Ctrl+C.

## Evidence and limits

Use [VALIDATION.md](VALIDATION.md) for executed tests and independent review, [REQUIREMENTS-MATRIX.md](REQUIREMENTS-MATRIX.md) for capability status, and [RECOVERY.md](RECOVERY.md) for a stopped backup and fresh-directory restore. Never restore over original data.

Production startup remains blocked. Real AD identity, SQL Server, Windows/IIS, scanner integration, retention/holds, source extraction/completeness and operational cutover/rollback require separate implementation, approved decisions and target-environment validation. Local USWDS, keyboard/mobile and axe checks do not establish accessibility compliance. AI and messaging integrations remain disabled.
