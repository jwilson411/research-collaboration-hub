# Migrated-link resolution

The Activity page can resolve a source-study/source-record pair within the current destination study. `GET /api/resolve` requires `studyId` and either both `sourceStudyId` and `sourceId`, or `sourceUrl` for an exact imported `legacy_url` value. It returns a local `#study/...` fragment and minimal current target metadata, never an HTTP redirect or fetched external content.

Destination membership is checked before looking in the import ledger. Missing, inaccessible, ambiguous, deleted and unavailable targets return the same 404 response. File targets additionally require current release policy, intact bytes and live ancestry. A version source identifier resolves its exact immutable target rather than the latest file version. Application administrator status alone provides no content access.

Source URLs must be bounded HTTP(S) values without credentials or control characters. Matching is exact: query strings, fragments, case and version identity are not normalized. Only the current imported source record's URL is indexed; earlier URLs retained inside source history do not gain aliases automatically. Multiple matching source URLs fail closed. Source identifiers and all route segments are escaped; caller-supplied destinations and redirect parameters are rejected.

This is a local resolution seam for imported synthetic records, not an external redirect service, crawler, source-system retirement plan or proof that all historical links were inventoried. Use the rehearsal inventory and reconciliation receipts to inspect submitted record/link outcomes, and establish real-source inventory and coexistence policy separately.

With the preview stopped, run:

```sh
DOTNET=/path/to/dotnet python3 tests/test_migrated_links.py
```
