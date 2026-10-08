# USWDS components and application composition

This application pins **USWDS 3.14.0** in `package.json` and `package-lock.json`. Its actual Sass and selected JavaScript component modules are built locally. CSS, JavaScript, fonts and images are committed and served from the same application; no CDN is required at runtime. The [official developer guidance](https://designsystem.digital.gov/documentation/developers/) describes the underlying asset and component model.

The component audit found that the earlier application loaded USWDS CSS but overrode standard control styling and used custom navigation, cards and native disclosures without the USWDS JavaScript lifecycle. This revision replaces those imitations with the component structures below. Study behavior remains application code.

## Component-to-screen map

| Screens or controls | Actual USWDS use | Application responsibility or deliberate difference |
| --- | --- | --- |
| Global shell | Basic header, primary navigation, mobile menu/overlay, skip navigation | Synthetic identity selector, hash routes and session invalidation. The footer is a simple application composition, not the USWDS footer component. |
| My studies and named brainstorming sessions | Card groups with card container/header/body/footer structure | Study counts, lifecycle labels, membership and navigation destinations. |
| Study navigation | Side navigation and breadcrumb structure, including current-page state | Selecting and loading study sections. |
| Buttons | Standard, outline and unstyled button variants | Mutation availability, request identifiers, pending states and error handling. |
| Forms across documents, tasks, decisions, resources, templates, administration and migration | Forms, fieldsets, legends, labels, form groups, text inputs, textareas, selects and hints | Domain validation and submission. Field widths and multi-column arrangements are application layout. |
| Evidence selection and orientation acknowledgments | Checkbox inputs with associated sibling labels | Exact evidence IDs, availability and acknowledgment persistence. |
| Attachment and manifest selection | Actual file-input JavaScript enhancement | File-size limits, synthetic validation/release rules, authorization and upload handling. Component selection is not a malware scan. |
| Document/file history, source provenance, decision history, templates and rehearsal details | Actual accordion headings, buttons, controlled panels and expanded state | Dynamic content, unique panel IDs and opening the exact historical record targeted by a link. |
| Search | Search-form structure and controls | Permission-aware results, filters, pagination queries and result cards. Previous/next pagination uses ordinary buttons, not the USWDS pagination component. |
| Notices and form feedback | Alert structure and variants; field error classes and associated error text | The adapter maps browser validation messages to fields. Server errors, live-region updates and recovery instructions remain application behavior; the USWDS validation JavaScript module is not bundled. |
| Administration, import outcomes and rehearsal inventory | Standard table styling | Captions, header associations, data projection and a keyboard-focusable horizontal overflow region on narrow screens. No sortable-table behavior is claimed. |
| Task plans, decisions, handoffs, receipts and accessible brainstorm lists | Standard controls/cards/disclosures composed with application panels and lists | Workflow, attribution, exact-version evidence, permissions, ordering and persistence. These are not standalone USWDS components. |

Lifecycle pills, count labels, evidence relationships, orientation steps, the synthetic notice and domain panels remain application compositions. They use design tokens for spacing and color but are not labeled as USWDS tag, process-list, summary-box or government-banner components.

Native date inputs are retained for ISO-formatted task and decision dates. The USWDS date-picker module is not installed into the page. Editors intentionally stay inline and focus their first field; they are not modal dialogs and do not claim modal focus-trap behavior.

## Sources, build and theme

- `assets/_theme.scss` shares USWDS settings: local font/image paths, global content styles and widescreen container/header widths. Standard component fonts, color choices and interaction states remain USWDS defaults.
- `assets/styles.scss` compiles the USWDS stylesheet. `assets/app.scss` adds application layout and domain composition using USWDS Sass tokens; its generated output is `wwwroot/app.css`.
- `assets/uswds-components-entry.js` imports the maintained accordion, file-input, header/navigation, button and skip-navigation modules. The build bundles them into `wwwroot/vendor/uswds/js/components.js` and exposes the application-owned `HubUSWDS` adapter interface. This interface is not a global API supplied by the stock USWDS browser bundle.
- `scripts/build-assets.mjs` compiles both stylesheets, bundles those modules, and copies the official initializer, fonts, images and license. `wwwroot/index.html` loads only these local assets plus the application scripts.

Run `npm ci`, `npm run build`, and `npm run check:frontend` to regenerate and syntax-check the assets. Edit the Sass and entry sources rather than generated CSS or vendored files. Node.js is needed for rebuilding; the committed assets support ordinary .NET preview startup without it.

## Dynamic views and behavior lifecycle

The shell initializes navigation, button, skip-navigation and delegated accordion behavior once. `wwwroot/uswds-components.js` enhances later application views: it creates the actual accordion heading/button/panel contract, initializes new accordions, adds the documented form/checkbox structure and initializes new file inputs. Existing native disclosures are an intermediate fallback before enhancement.

The adapter moves existing controls instead of cloning them so selected files and session-context bindings stay associated with their original nodes. Repeated enhancement skips controls already enhanced. Removed file-input trees run the official teardown, using a detached host if needed; private content is not reattached to the visible document. File inputs retain a purpose label and associated instructions. Historical-link focus opens containing native or USWDS disclosures before focusing the target.

The application's session checks, asynchronous response guards, draft recovery and server authorization remain separate from this visual lifecycle. Component enhancement must not become an alternate submission or permission path.

## References and verification limits

Official guidance: [component catalog](https://designsystem.digital.gov/components/overview/), [header](https://designsystem.digital.gov/components/header/), [cards](https://designsystem.digital.gov/components/card/), [forms](https://designsystem.digital.gov/components/form/), [side navigation](https://designsystem.digital.gov/components/side-navigation/), [accordion](https://designsystem.digital.gov/components/accordion/), and [file input](https://designsystem.digital.gov/components/file-input/).

The application intentionally does not reproduce the [official-government banner](https://designsystem.digital.gov/components/banner/), a government seal, or a claim of government ownership or approval.

The focused `tests/uswds-browser.mjs` Chromium journey passed actual component checks: mobile menu dismissal and focus return, skip navigation, cards and current side navigation, keyboard checkbox persistence, field errors and summary links, keyboard accordions and exact-history focus, enhanced file selection and upload, and status alerts. Ten selected desktop/mobile axe checks reported zero violations, with no page overflow, page errors or external requests. Independent review found and corrected search restructuring, an unlabeled identity region, the mobile search button name, alert live priority, and focus lost during control enhancement. The existing full workflow suites and server regression suite are separate publication gates. Selected keyboard, responsive-layout and automated accessibility checks do not establish full WCAG or Section 508 conformance, and component use does not establish production security or an authorization to operate.
