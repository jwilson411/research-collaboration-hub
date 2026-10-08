# Research collaboration hub

A local, synthetic research-study collaboration preview built with ASP.NET Core 10 and the U.S. Web Design System. It is not an official government service. No actual research or patient data belongs in this demo.

## Morning quick start

Check out `feature/local-study-hub`. Install a currently serviced [.NET 10 LTS SDK](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core). `global.json` selects the latest installed stable .NET 10 feature band; newer major SDKs do not replace that requirement. Built USWDS assets are included, so Node.js is only required when rebuilding the frontend.

```sh
git clone --branch feature/local-study-hub https://github.com/jwilson411/research-collaboration-hub.git
cd research-collaboration-hub
```

Windows PowerShell:

```powershell
./scripts/Start-LocalPreview.ps1
```

Linux or macOS:

```sh
./scripts/start-demo.sh
```

Open http://127.0.0.1:5080 **on the development computer**. A phone's localhost does not reach that computer. Both launchers pin Development and the JSON demo provider, restore locked packages, and quarantine all uploads by default. For the file walkthrough, use `./scripts/start-demo.sh --release-synthetic-files` or `./scripts/Start-LocalPreview.ps1 -ReleaseSyntheticFiles`. These explicit switches release only validated text and the bundled synthetic PNG. Inherited SQL provider and file-release settings are ignored. Existing `HUB_DATA` and `HUB_FILES` overrides remain available; choose empty paths for a fresh demo. The PowerShell launcher restores its process environment when it exits; Windows execution remains untested here. Stop with Ctrl+C. There are no LAN listeners, tunnels, hosted CI, AI requests or messaging integrations.

The application requires explicit demo enablement and Development, validates loopback remote address and Host, and refuses Production startup. Any local visitor can select a synthetic identity: this is a demonstration mechanism, not production authentication. Alex, Casey (reviewer) and Riley (study lead) have Atlas access; Sam has Beacon access; Morgan manages application roles/mappings without automatic study access. Synthetic group membership is immutable and does not become an editable roster.

## Guided walkthrough

Fresh state includes an entirely synthetic checklist-review and handoff journey. See [document review and handoff walkthrough](docs/DOCUMENTS-HANDOFFS.md) for the complete author → reviewer → study lead → returning collaborator sequence. Existing saved workspaces are preserved; select a separate empty `HUB_DATA` path for fresh fixtures.

1. As Alex, open Atlas. Review its documentation and discussion. Select an exact text or released file version as the current study protocol, with a reason. This is a workspace designation, not an external approval. Uploading a newer version does not change it.
2. Open Tasks & decisions. Create a task with Alex as assignee, a due date, status and exact document/discussion/file-version evidence. Edit it and inspect the retained earlier revision.
3. Restart with the explicit synthetic release switch above, then open Document library. Upload a small `.txt` file and download it. Upload `fixtures/demo-attachment.png` to demonstrate a verified-byte binary round trip. Upload a PDF to see quarantine: its download remains blocked. Use New version to retain a file's earlier version.
4. Attach a file to a discussion/reply. A deleted parent makes its attachment unavailable. Record an idea and promote it into a linked decision.
5. Switch to Sam: Atlas URLs, search and downloads are inaccessible. Reopen Beacon to continue its historical record. Switch to Morgan to inspect roles, mapped groups, effective access and audit. Two open admin forms cannot silently overwrite one another: stale configuration is rejected.
6. To rehearse ingestion, Morgan grants Alex the Administrator application role. Alex still has only Atlas study access. Return as Alex, open Atlas's Activity & lifecycle → Synthetic import rehearsal, choose `fixtures/app-import.json`, preview all record outcomes, then apply. Inspect the imported file versions, historical thread/reply, attachment and decision evidence. Repeat the manifest: no duplicate records or versions are created.
7. Submit edits from two tabs. A stale submission is rejected and its draft stays in the form. Stop/restart: saved state persists.

Explore [brainstorming sessions and personal orientation](docs/BRAINSTORMING-ONBOARDING.md) for the next part of the synthetic journey: keyboard ordering, exact idea-to-decision evidence, archive/reopen, and context-aware personal checklists.

## Persistence and attachments

The default single-process JSON provider stores metadata in `.data/hub.json`; `HUB_DATA` overrides it. Immutable file bytes live in sibling `.hub-files`, **outside the application directory**, or an explicit `HUB_FILES` directory. Back up metadata and blobs together while the preview is stopped. Do not store attachment bytes in webroot or the application directory. Ignored local data and screenshots are not published.

Uploads are limited to 512 KiB decoded and 1 MiB requests. Allowed types are `.txt`, `.pdf`, `.png`, `.jpg`; filenames, UTF-8 text or signatures are validated. All uploaded bytes get SHA-256 integrity metadata and generated storage names. Downloads check current study membership, parent/deletion state, release policy and checksum, and force attachment disposition with `application/octet-stream`.

**There is no malware scanner.** The optional synthetic policy releases validated text and only the exact bundled PNG. Other binaries remain quarantined. Deleted and interrupted/unreferenced blobs are not automatically destroyed: reviewed retention and orphan cleanup are future work.

`IStudyStore` also has a bounded SQL Server snapshot adapter with explicit schema setup and synthetic import command. It is not a normalized production data model, and was not tested against a live SQL Server here. See [storage](docs/STORAGE.md) and the [IIS deployment gate](docs/IIS.md).

## Build and checks

```sh
npm ci
npm run build
npm run check:frontend
dotnet restore --locked-mode
dotnet build --no-restore
python3 -m unittest discover -s tests -v
```

The HTTP suites require `dotnet` on PATH (or set `DOTNET` to its executable), and exclusively own loopback port 5080. Stop the preview first. The browser smoke script runs against a disposable, already-running demo with a separately installed Playwright/Chromium; see its opening instructions. No hosted CI is configured.

See [feature matrix](docs/FEATURES.md), [synthetic migration rehearsal](docs/MIGRATION.md) and [next milestones](docs/NEXT.md). This preview is not production-ready or an accessibility compliance certification.

Decision supersession, versioned templates and resource history: [walkthrough and limits](docs/DECISIONS-RESOURCES.md).

Stopped synthetic JSON/blob backup and isolated restore: [recovery procedure](docs/RECOVERY.md).

For a complete generic capability audit and next priorities, see the [requirements evidence matrix](docs/REQUIREMENTS-MATRIX.md). It distinguishes local implementation, demonstrations, disabled modules and missing capabilities.
