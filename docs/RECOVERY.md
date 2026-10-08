# Synthetic local demo recovery

`tools/backup_demo.py` creates and restores an offline snapshot of the JSON demo and its referenced attachment blobs. It is not a SQL Server backup tool or a production recovery procedure. Use only trusted, synthetic demo data. The `SyntheticDemo` dataset marker is an eligibility assertion, not a sanitizer; never add it to real data to bypass refusal.

Freshly seeded demos carry the dataset marker. Older saved datasets without it fail closed rather than being automatically relabeled; use a separate fresh synthetic demo for this rehearsal.

Stop the application completely before both creation and restore. `--stopped` acknowledges this responsibility; the tool also refuses if the normal loopback listener on port 5080 is active. That probe cannot prove that another process or a differently configured listener is stopped. Before/after metadata checks catch changes during creation, but do not make a live backup safe.

Use dedicated existing directories outside the repository, webroot, source directories, and system/credential directories. Supply your own absolute paths in these examples:

```sh
python3 tools/backup_demo.py create --state "$DEMO_SOURCE/hub.json" --blobs "$DEMO_SOURCE/files" --output "$DEMO_ARCHIVES/synthetic.zip" --stopped
python3 tools/backup_demo.py verify --archive "$DEMO_ARCHIVES/synthetic.zip"
python3 tools/backup_demo.py restore --archive "$DEMO_ARCHIVES/synthetic.zip" --parent "$DEMO_RECOVERY" --name demo-restore-check --stopped
```

The archive output must not already exist. Restore requires a fresh destination named `demo-restore-` followed by a simple lowercase token. Restore never overwrites or repairs the original dataset. It returns paths for `HUB_DATA` and `HUB_FILES`; configure those paths explicitly before starting the isolated Development demo. Keep the listener on `127.0.0.1:5080`. Existing accounts/groups remain synthetic; no directory, credentials, or authentication keys are restored.

The archive contains exact JSON metadata and every immutable blob referenced by current records or retained handoff snapshots, including retained deleted-file records. Unreferenced orphan blobs, server logs, authentication key stores, environment variables, and arbitrary neighboring files are excluded. Do not publish the archive; the retained metadata includes histories and tombstones. Synthetic identity/group and credential-field checks are additional refusal checks, not comprehensive sensitive-data detection.

Each allowlisted archive member has a size and SHA-256 checksum; the canonical manifest has its own SHA-256 checksum. Validation rejects extra members, path traversal, symlinks/reparse points, duplicate names, inconsistent references, excessive sizes, and mismatched bytes. These checks detect corruption, not malicious replacement or authenticity. The tool reads and writes fixed names without general ZIP extraction. It stages new output, synchronizes files, and publishes without replacing an existing destination. Interrupted staging may require operator cleanup; this is not a tested guarantee against power loss or hostile concurrent filesystem mutation.

Archive verification does not validate application-domain handoff digests. After restoring, sign in through the local demo, open each required handoff, download selected evidence, verify document versions and permissions, and confirm original data remains unchanged. A handoff detail request verifies its stored digest in the application. Never silently reset or reseed a failed restore.

The repeatable automated checks are:

```sh
python3 tests/test_backup.py
DOTNET=/path/to/dotnet python3 tests/test_recovery_rehearsal.py
```

The rehearsal owns loopback port 5080, creates disposable synthetic data, stops the app, creates/verifies/restores the archive, restarts against a fresh destination, and checks exact metadata, immutable snapshots, downloaded bytes, replay behavior, negative access, and source preservation. Run it while the preview is stopped. Linux is the validated platform. Windows reparse-point checks and exclusive rename paths are implemented but untested; Windows/IIS recovery and production SQL Server recovery need separate operational validation.
