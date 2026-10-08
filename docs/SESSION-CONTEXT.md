# Synthetic session context and retained drafts

The identity selector is a local demonstration feature, not production authentication. Tabs in the same browser cookie context share the selected synthetic identity. Switching identity must not silently save another tab's draft under the new actor. Production startup remains disabled.

## Server boundary

The server keeps a random session identifier in the `hub.session` HttpOnly, SameSite=Strict cookie. The selected actor and a separate random generation token remain in server memory. `GET /api/session` returns the current generation as `sessionContext`. API mutations must send it in `X-HUB-SESSION`; missing, expired or mismatched context returns HTTP 409 with `code: session_changed`. Refreshing the session does not automatically retry the rejected operation. CSRF validation remains a separate requirement.

Each session has a serial request gate. The server captures the actor under that gate and holds it through endpoint execution. An identity switch rotates the generation. A write admitted before the switch can finish under its original actor before the switch is acknowledged. An old-generation write admitted afterward is rejected. This prevents accidental attribution changes; it does not undo an already committed write. Domain authorization, object availability, revision checks and request-id handling still run for accepted requests.

Session state is memory-only, limited to 1,024 sessions, with eight-hour idle expiry. Server restart invalidates outstanding contexts. An unknown or expired mutation cannot silently establish a default identity. Read requests can establish a new synthetic session; capacity exhaustion returns 503. These are single-process preview mechanics, not distributed sessions or a validated IIS/AD identity design.

## Browser behavior

Controls and asynchronous operations capture their originating actor, session generation, authorization context and route. File reads and deferred requests retain that context. A later response must not replace the current screen or submit its old draft using a freshly selected identity.

Tabs signal context changes through BroadcastChannel and a storage-event fallback. The client also checks the session on focus, visibility restoration and back/forward-cache restoration. It hides the workspace while revalidating, invalidates stale work and clears study/search/editor caches. The server token check remains necessary when a notification is delayed or unavailable. Suspended tabs and already downloaded content cannot be remotely erased.

Configuration changes are reflected in the session's authorization context. This is a browser invalidation signal; it does not replace current server-side role and study-group checks. Connection or verification failure does not authorize a pending draft to continue.

## Draft recovery and its limits

On invalidation, edited forms and selected files can be retained in the originating tab's memory, associated with their original synthetic identity. Recovery offers an explicit download only for the original identity after current study-access checks. Administrative forms also require current Administrator access; template-definition drafts require the current StudyLead role. The same checks apply to recovery of selected files. It does not restore an old revision into a form, replay a request, grant membership or submit content automatically. Return to the original identity and review the shared record before starting a fresh form.

An interrupted request may already have committed under its original identity even if its response was discarded. Inspect the saved record and audit history before recreating the work; do not treat a network interruption as proof that nothing was saved.

**Closing or reloading the tab, browser termination, or loss of the page's memory loses retained drafts and selected files.** This recovery store is not a durable backup. Export permitted drafts before leaving the page. Selected files remain local browser objects until explicitly downloaded or submitted through a fresh authorized workflow. Downloaded exports are ordinary local files and are no longer controlled by the application.

## Verification status

The complete suite passed 199 tests, including eight focused session cases. Five independent browser suites passed, including the cross-tab reproduction, delayed operations and access-revocation recovery. See [the validation record](VALIDATION.md) for exact results and corrected review findings. These checks do not establish production identity, complete browser isolation or a data-loss guarantee.
