# Dashboard path routes

The workbench uses document paths. Its local base is empty; hosted shells pass
`basePath: "/orgs/<encoded-slug>"` to `mountUniverseApp`. A page address is
`BASE/view[/detail]`, or `BASE/deployments/tab[/detail]`, plus its query string.
The root base opens Strategy, subject to the existing last-page preference.
The last-page preference saves the destination and its query without `project`
or `selection`; replay uses that screen's saved scope. A deep link or history
entry applies scope in the current tab only. Project preferences change on
explicit picker choices or removal of inaccessible project IDs, never on
navigation or a default focus. Returning to a tab re-reads the actor's saved
selections; only a change to saved selections or focus re-renders the route and
replaces its query scope. An unchanged read preserves the current deep link and
page contents. A picker choice made during that read wins.

`yoke_core/ui/contracts/dashboard-routes.json` ships in the product wheel.
Hosts read `views`, `tabs`, `localBasePath`, and `hostedBasePathTemplate` from
that file to serve the same shell on deep GET paths. The roster is generated
from `static/universe_destinations.js`; after changing NAV, run
`yoke dev run -- python3 -m yoke_core.ui.dashboard_routes sync --target-root <checkout>`.
The contract check compares the emitted roster to NAV. The local server admits
only those paths through its existing token/cookie gate, and serves assets at
`/assets/` independently of the current page depth.

Host helpers exported from `static/app.js` and declared in
`contracts/universe-app.ts` use these signatures:

```ts
buildUniverseRoute(view, project = null, segment = null, detail = null, basePath = "", navigation = [])
parseUniverseRoute(href, basePath = "", navigation = [])
withProjectSelection(href, selections, basePath = "", navigation = [])
```

`selections.selectionFor(view)` answers `"all"` or an array of project IDs.
Project selection remains in the query: `project=1,2` on lists; `project=1`
addresses detail/focus resources, with `selection=1,2` carrying the list scope.
An explicit selection wins. The host passes its base to its helper calls.

Ordinary links and row navigation use the mount's history owner. Real user
navigation pushes one entry; canonicalization replaces the current entry.
Entry bookmarks containing `#/view` are converted once to the corresponding
path, including the fragment query. `popstate` handles browser Back/Forward.
Flows Back returns to the previous app entry when one exists, otherwise the
Flows list. Page changes and project switches scroll to the document top.
Back/Forward leave scrolling to the browser. Nothing saves or restores scroll.

Hosted contract changes require a companion consumer build against the exact
candidate. Land the producer and consumer before the joint hosted release;
the normal release bridge proves that exact pair before publication.

Host page sections use `UniverseSectionContent`: an Element or a synchronous
factory receiving `{ universeId, scope, projectSelection, signal }`. The host
passes `universeId` with its selected universe and matching client, and unmounts
before mounting another universe; standalone mounts report null. `scope` is the
same resolved value the Yoke renderer receives: `"all"`, project IDs as an array,
a single focus ID, or null on unscoped pages. `projectSelection` preserves the
picker's All/one/multiple selection independently of focus and detail routes.
Factories run when their page is rendered, including held-data scope changes;
their previous signal aborts on scope changes, route changes, and unmount.
Pass it to fetch and check `signal.aborted` before applying asynchronous results.
Slots retain their zero-argument factories. Section nodes remain host-owned and
are detached when replaced or unmounted. A null factory result hides the section
until its next render. Factory failures show `host_section_render_failed` with
recovery on the affected page. `beforeScope` controls visual placement, while the
factory still receives the current selection so it can choose its own use of it.
On a scope-less page `beforeScope` leads the page, above the view's own content,
and `inView` follows that content; Team's seat section uses `beforeScope`.
Team also reads `capabilities.data.team.seatsLeft` once at mount: a
non-negative integer adds a seats-left count to the Invites header and the
invite form for people who can invite (at 0 the form names Billing and
revoking a pending invite), and anything else draws no seats line.
The retired `members` path stays in the route contract and opens Team.

The TypeScript source declares the mount contract version. After changing it,
compile `contracts/tsconfig.json` with the UI's pinned TypeScript compiler and
commit both the declaration emit and runtime `static/contract-version.js`.
Hosts materialize types and static assets from the same pinned product revision.

Hosts add their own destinations through `UniverseAppOptions.navigation`, a
readonly array of `UniverseHostNavGroup` values from
`contracts/universe-host-navigation.ts` (also re-exported by `universe-app.ts`):

```ts
navigation: [{
  id: "host-tools", label: "Host tools", collapsible: true, pages: [{
    id: "reports", label: "Reports", icon: "items",
    content: ({ detail, signal }) => renderReport(detail, signal),
  }],
}]
```

Each group has `{ id, label, pages, collapsible? }`; each page has
`{ id, label, content, icon? }`. Both new fields are optional; hosts omitting
them keep their existing behavior. `icon` names an existing key in
`static/universe_nav_icons.js`: Lucide SVGs keyed by Yoke view ids (for example
`items`), rather than Lucide icon names or host-supplied SVG. An unknown key
leaves the icon slot blank and never refuses mounting.

Set `collapsible: true` to use the same disclosure control and remembered state
as Diagnostics. A group never opened starts closed. State persists through
`ui_preferences.nav_group.set/list` by group id matching
`^[a-z][a-z0-9-]{0,63}$`; longer valid group ids still render and toggle but
silently do not save. Host group ids `diagnostics` and `settings` share those
built-in groups’ saved state.

Groups follow Diagnostics in host order, and empty groups do not appear. Group
ids are unique lowercase slugs. Page ids are lowercase slugs unique across all
host groups. A Yoke view id or moved view id refuses mounting with
`host_page_id_reserved`, naming the id; choose a distinct id and remount.
Malformed or duplicate ids refuse with `host_page_id_invalid` or
`host_group_id_invalid`; fix the named slug and remount.

A page opens at `BASE/<pageId>[/<detail>]`, with its label in the page head,
sidebar, and browser title. Pass the same navigation array to exported route
helpers (including `universeNavScope`) when building host links outside the
mount. Host anchors inside the mount use app history, including detail links.
The host's HTTP handler must serve its mount shell on these declared page
paths, in addition to the built-in dashboard route roster, so reloads and deep
links work. The built-in roster does not enumerate host-owned pages.
Route canonicalization preserves a host page's query string and fragment,
including on reload. Hosts own these values; Yoke does not parse or filter them.

Content is an Element or synchronous factory receiving `UniverseHostPageContext`:
`UniverseSectionContext` plus decoded `detail: string | null`. Host pages have
`scope: null` and `projectSelection: "all"`; they take no project query scope.
Signals abort on navigation and unmount, and nodes detach for reuse. Null factory
results leave the body empty; a failing factory aborts its signal and displays
`host_page_render_failed` with recovery on the affected page.

The host decides access by omitting groups the viewer may not see. The
workbench does not infer permissions. Mounts without navigation keep their
existing destinations and route behavior: unknown pages still open Strategy.
The contract version remains 11; hosts consume the new declarations with the
same pinned workbench bundle.
