# Dashboard path routes

The workbench uses document paths. Its local base is empty; hosted shells pass
`basePath: "/orgs/<encoded-slug>"` to `mountUniverseApp`. A page address is
`BASE/view[/detail]`, or `BASE/deployments/tab[/detail]`, plus its query string.
The root base opens Strategy, subject to the existing last-page preference.

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
buildUniverseRoute(view, project = null, segment = null, detail = null, basePath = "")
parseUniverseRoute(href, basePath = "")
withProjectSelection(href, selections, basePath = "")
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
