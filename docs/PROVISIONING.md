# Synthetic study provisioning

An application administrator can create an empty synthetic study with `POST /api/admin/studies`. This local Development feature requires the dataset's existing `SyntheticDemo` marker. It refuses unmarked datasets instead of relabeling them. It makes no directory calls, creates no users or groups, and adds no members.

The request contains `studyId`, `title`, `summary`, `groupId`, `expectedRevision`, and `requestId`. The identifier is a stable, unique slug: 3–48 lowercase letters, digits and single hyphens, starting with a letter and ending with a letter or digit. Title and summary limits are 180 and 2,000 characters. Choose an existing synthetic group explicitly: `demo-group-a` or `demo-group-b`. `expectedRevision` is the global configuration revision returned by `GET /api/admin`; `requestId` is a fresh UUID retained for an exact retry.

New studies start **Paused**, at revision 1, with no documents, tasks, files, handoffs, or accepted content. Shipped template outlines remain available for later use, with exact default identities scoped to the new study. A mapped study member can explicitly reopen the study before contributing. Administrative access alone never grants access to its content; the synthetic administrator has no study-group membership.

The response returns `studyId`, `configRevision`, `initialStage`, and `initialGroupId`. The initial values describe provisioning, even if a later retry occurs after the workspace has changed. Configuration history and audit record the creation, and the study stores synthetic provenance: actor, time and initial group. Directory membership remains unchanged.

Duplicate identifiers, stale revisions and request-ID reuse for different operations return 409. Malformed requests return 400. Current administrative authorization is checked before replay, so a revoked administrator cannot replay a successful creation. Exact retries create no additional study or audit event. A local persistence failure returns 503 with no in-memory commit; restore storage access and retry the original request.

This is not a production onboarding or directory provisioning workflow. Production identity, group discovery, approval policies and Windows/IIS integration remain separate implementation and validation work.

Run the synthetic loopback checks with the preview stopped:

```sh
DOTNET=/path/to/dotnet python3 tests/test_provisioning.py
```
