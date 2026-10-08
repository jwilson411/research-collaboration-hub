# Document review and handoff preview

This is a synthetic collaboration workflow. Workspace acceptance, protocol designation and handoff capture are not formal study approval or a digital signature.

## Immutable document versions

Each text document family has a stable ID independent of its title. Creating a revision produces a new item ID, content, author and timestamp, with the exact prior version ID. Content is never edited in place. Legacy document records remain distinct singleton families; matching titles do not silently combine histories. Existing imported binary families remain separate exact file versions with their original provenance.

Review state and its event history are stored separately from immutable text. In this demo, Alex and Sam are Researchers; Casey is a Reviewer; Riley is a StudyLead. Every operation still requires current mapped group membership. Application Administrator is not a study-review role and grants no study membership. These fixed synthetic role claims are not a production directory integration or a configurable membership roster.

| Transition | Allowed synthetic study role |
|---|---|
| Draft → Review | Researcher, Reviewer, StudyLead |
| Review → Draft | Reviewer, StudyLead |
| Review → Accepted | StudyLead |
| Accepted → Superseded | StudyLead |

Every transition requires a reason, current study revision and request identifier. Only one live version per family may be Accepted; explicitly supersede the old version before accepting the replacement. A currently designated protocol must be reassigned or cleared before superseding it. Protocol designation is an independent working-reference choice and does not change a document's review state.

Accepted and superseded text versions are retained. Referenced draft versions cannot be deleted while live study content depends on them. Accepted file evidence must be available and integrity-verified at acceptance, and retained file references cannot be removed through normal deletion. Actual file loss, changed release policy or storage damage can still make evidence unavailable; this preview is not a recovery guarantee.

## Immutable handoffs

A capture records its study revision, purpose, exact documents/files, current task versions, decisions, open conversations, review history, authors/times and original provenance. Exact evidence and structural context are included. Earlier task-edit histories remain with the source task; the capture contains the task version selected at capture time. Later task changes, review transitions, lifecycle closing or reopening do not rewrite it.

Choose an explicit subset when the workspace contains unavailable evidence, quarantined files or more than the bounded capture permits (50 items, 30 files, 1 MiB). A capture never silently substitutes newer evidence. It requires an active study and rejects stale requests. Identical retries reuse the saved snapshot.

Current membership is checked on every read. Removed source content is masked in the snapshot's read projection; unavailable file versions cannot be downloaded. The original stored capture and SHA-256 remain unchanged. The displayed digest covers the original capture, not a redacted projection, and is a content fingerprint rather than a signature. Raw captures are not returned through study-list or study-detail APIs. Reading a capture whose stored fingerprint no longer matches fails closed with an integrity error; the fingerprint is not protection against an operator able to rewrite both data and digest.

## Synthetic morning journey

Fresh demo state includes a first checklist outline marked Superseded, its Accepted working edition, a rationale decision, an unresolved orientation question, an assigned rehearsal task, a brainstorming idea and a baseline handoff. All authors, dates and events are synthetic fixtures. Existing saved workspaces are not overwritten with new fixtures; use a separate empty `HUB_DATA` path to explore fresh state.

1. As Alex, open Atlas and read “New or returning? Start with this synthetic journey” in Living documentation.
2. In Document library, inspect the working checklist's review history and its prior outline. Revise the working edition with a changed title: the family stays the same and the new version starts Draft.
3. Submit the new version for Review. Switch to Casey to return it with a reason; Alex can submit it again. Riley can supersede the previous Accepted edition, then accept the replacement. Inspect authorship and event history.
4. Add a small synthetic text file and link its exact version to a task or decision. A newer uploaded file does not alter those citations.
5. Open Handoffs. Inspect the seeded baseline and create a new capture containing the working checklist, decision, task and open question. Include the linked file evidence.
6. Update the source task. Reopen the earlier snapshot: it retains the previous task version and context. Close and reopen the study; captures stay intact.
7. Switch to Sam or Morgan to confirm Atlas remains inaccessible. Administrator status never bypasses study membership.

Windows/IIS, real directory roles, formal approval workflows, immutable audit infrastructure, signatures, live SQL, production recovery and records-policy disposition require separate implementation and validation.
