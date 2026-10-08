# Decisions, templates and resource pointers

These are synthetic collaboration records, not formal study approvals.

## Current guidance and retained history

The task view separates open tasks, current decisions and superseded history. Recording a decision preserves its rationale, alternatives, responsible participant, effective date and exact item/file evidence. A Reviewer or StudyLead can replace a decision with a new immutable record and a required explanation. The earlier record remains readable and links to its replacement. Only one successor is permitted; stale writes conflict and exact retries return the recorded result. Study membership is checked before role and retry handling. Application administrators gain no study membership from their role.

A decision's current/superseded status is derived from the retained chain. Supersession never changes an earlier rationale or retargets evidence to a newer version. Brainstorm-derived decisions retain their exact idea version through the chain. Superseded records and replacements cannot be deleted through the generic removal or import paths. Changed imported decisions need distinct source records or explicit supersession; imported rationale cannot overwrite an existing decision.

Handoffs capture decision status and exact evidence at capture time. Later supersession does not rewrite that capture. Current access and source removal checks still apply when viewing a capture; unavailable records are masked. Checksums detect changed stored captures, not signed approval. Closed studies must be reopened before recording or superseding decisions.

## Starting documents

Documentation offers three bundled outlines: study protocol, handoff notes and collaborator orientation. Choosing one fills editable title/body fields. Saving creates a new Draft document family with template ID/title provenance; subsequent versions retain the origin. It neither accepts the document nor selects the current protocol. These are useful starting outlines, not a governed or versioned template catalog.

## Resource pointers

Record a local description or HTTP(S) URL, a current study-member owner, the source, and a past/current verification date. The app never fetches the URL or asserts its accuracy. Browser links open only after a user activates them. Credentials in URLs and executable/file schemes are rejected. An older verification date is a visual prompt to check the pointer, not a background monitoring service.

Pointers are create-only records in this milestone. Replace an outdated pointer with a newly verified record and remove the old one where retention policy allows; there is no automatic refresh or governed attestation workflow. Explicit handoffs can capture a pointer and its metadata. Removal masks that captured source on subsequent views.

## Morning walkthrough

1. As Alex, open Atlas and inspect the next action's owner, status and due date; open a question directly from the overview.
2. Open Tasks & decisions, record a synthetic decision with exact evidence, and capture it in a handoff.
3. As Casey (Reviewer), replace the decision with a reason. Compare Current decisions and Superseded history; reopen the earlier handoff to see its captured state.
4. In Documentation, choose the protocol outline, edit the text, and save. In Library, confirm its Draft state and template origin.
5. Add a resource pointer with Alex as owner and an explicit source/date. Confirm the app labels it as a recorded pointer rather than a live integration.

## Usability review and fixes

Independent review found that the mixed task/decision feed obscured current guidance, the overview omitted who/when for an action, and a supersession form could lose sight of the rationale it replaced. The preview now separates open tasks/current decisions/superseded history, collapses completed tasks, shows owner/status/due date on the overview, links directly to conversations, and displays the immutable prior rationale beside the replacement form.

Template creation goes directly to the document library and labels its Draft origin. Resource metadata distinguishes a contributor-entered verification date from any application check. Captures label historical decision state explicitly. Document and file families now keep relevant current, accepted/released and designated protocol versions visible while placing earlier versions in native disclosure controls. Exact historical links expand the relevant history and focus the cited record.

Fresh synthetic orientation content uses separately spaced, semantic numbered steps. Existing saved document bodies are retained. The independent browser review verified historical disclosure navigation, mobile layouts and the decision, template and resource flows without a blocking usability defect.
