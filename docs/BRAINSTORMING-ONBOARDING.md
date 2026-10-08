# Brainstorming and returning collaborators

The local preview uses named brainstorming sessions with an ordered list as the primary shared surface. The same content is available as a readable summary and an authorized text download. It needs neither drag gestures nor external whiteboard services.

## Sessions and exact idea history

Create a session with a purpose and a responsible current study participant. Assignment never grants study access. Add ideas, move them up or down using buttons, and revise their text. Each edit creates a new immutable version ID under the same logical idea; the earlier author, time and content remain available.

A decision can cite any retained exact version, including an earlier one. Its rationale is a separate record. The idea shows its linked decisions, and the decision links back to its session and source revision. Later idea edits do not rewrite a decision's evidence. Handoff capture follows that exact reference.

| Operation | Synthetic study role, after current group membership check |
|---|---|
| Create/edit sessions or ideas, reorder, record decisions | Researcher, Reviewer, StudyLead |
| Remove an unreferenced logical idea and its versions | Researcher, Reviewer, StudyLead |
| Archive or reopen a session | Reviewer, StudyLead |
| Read or download a session | Current study group member |

Application administration does not bypass membership or study roles. All new session mutations require an Active study. An Archived session remains readable; reopen it before changing its metadata, ideas, ordering or linked decisions through the session. Existing identical retries return the saved operation's current authorized projection without creating another event.

Archive preserves the session's idea record; it does not freeze every external linked record. Removing a decision through the study's normal removal path can change the reverse association shown in an archived session. Current task/evidence references prevent idea removal; references held only in historical task revisions or handoff captures may become explicitly unavailable after removal. Handoff read projections continue to mask removed source content.

Study revisions prevent stale overwrites. Request identifiers prevent duplicate ideas, revisions, reorder events and decisions on repeated submissions. Idea removal rejects live references, then masks all versions in study/search/session/export responses. Generic item deletion and generic idea-to-decision routes cannot bypass the managed session rules.

Session history records actions, actors, times, reasons and before/after metadata and order. It does not embed copied idea bodies. The readable export contains current session metadata, retained idea versions and their decision references; it is not an immutable handoff snapshot.

## Personal orientation

The study overview offers four personal acknowledgements: working guidance, latest handoff, unresolved conversations and next actions. A resume link leads to the next available incomplete step. Each acknowledgement records the exact current context and time, not merely a checkbox against a permanently fixed label.

New guidance, changed imported conversation text, a new reply, a changed task or a changed handoff projection makes the relevant step incomplete again. A stale submission cannot claim the person reviewed new evidence. The checklist belongs to the signed-in synthetic identity; another participant's progress is not returned by study or checklist APIs.

Personal acknowledgement changes only personal progress. It never accepts a document, changes study membership or modifies the study revision. It remains available while a study is paused or closed because reviewing retained material does not edit the study. Reopening is still required for new study/session content.

## Morning walkthrough

1. Start fresh synthetic state and open Atlas as Alex. The overview shows the personal orientation checklist and study contact. Review a step, acknowledge it with the keyboard, and navigate away/back to see it persist.
2. Open Ideas & whiteboards → Returning collaborator workshop. Read the two versions of the starting-point idea and the decision citing version 2.
3. Create a new session, add two ideas, and use Move up/Move down. Focus remains on the moved idea; its new position is announced. Use Readable summary or Download summary for the equivalent linear record.
4. Edit an idea. Record a decision from its earlier version and inspect the source link in Tasks & decisions. The older idea text remains the evidence.
5. As Casey or Riley, archive the session with a reason. Its content stays readable. Reopen it to continue; closed studies must first be reopened in Activity & lifecycle.
6. Return to the overview as another participant: personal completion is independent. Add a discussion reply or update a task and verify the affected earlier acknowledgement now needs review.
7. Capture a handoff containing the decision. It includes the exact source idea revision, independent of later session edits.

The fixtures, identities, roles and history are entirely synthetic. Keyboard/mobile/automated accessibility checks cover exercised flows only; screen-reader testing and accessibility acceptance remain outstanding. There is no shared live cursor canvas, AI generation, messaging traffic or production directory integration.
