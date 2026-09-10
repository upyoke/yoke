# Project selection in the shared app

The top navigation remembers All, one project, or a set of projects
**independently for each destination** — Sessions, Inbox, Overview, and every
other screen each keep their own selection across navigation, reload, and a
second tab. Changing one screen's selection never rewrites another's. Global
screens keep the selection visible and label their content as universe-wide.
A screen needing one project has a separate **Focus project** control;
changing it does not replace the remembered selection.

Selections are actor- and universe-scoped server state, not browser storage:
the shell fetches every remembered per-screen value in one
`ui_preferences.screen_selection.list` call before the first render, and
writes a screen's new value with `ui_preferences.screen_selection.set` when it
actually changes. Both are dispatched as the resolved operator actor (the
local UI proxy resolves it server-side; a hosted host authenticates its own
caller), and are stored in the generic `actor_ui_preferences` table under a
`screen.selection.<view id>` key, so the same value follows that actor across
reload, a new tab, or a different browser. Without a resolved actor, the list
read reads back empty and the write refuses; every screen simply renders at
its own "all" default. An unsuccessful initial read is never treated as
"confirmed empty": the shell tracks whether that read genuinely succeeded and
withholds every write until it does, so a transient outage cannot make a
route-driven default clobber whatever the actor's real preference already is.
A write that resolves with `success: false` (a denied or failed save) and one
that outright fails the network call are both surfaced the same way — a short
notice next to the scope picker — rather than silently looking saved. All
selection and focus IDs are revalidated against the accessible project
roster on every render.

Routes use `project=all` or comma-separated project IDs for selection on list
and global destinations. On detail and single-project destinations, `project`
addresses the resource/focus and `selection` carries the remembered selection:
`#/strategy/PLAN?project=2&selection=1,2`. An explicit deep-link selection wins;
without `selection`, an explicit `project` initializes selection. An absent
scope preserves that destination's current preference. The shell replaces an
incomplete URL with its resolved scope without adding a history entry, so
back/forward can restore All independently of later changes.

Hosts use the exported `withProjectSelection(hash, selections)` for ordinary
navigation, where `selections` is the shared per-screen state object; it looks
up the TARGET route's own view to decide what to carry, never the currently
active screen's value. The shared shell applies it to its own and
host-provided anchors and to renderer navigation callbacks. It preserves
explicit selection and resource project values. Hosted route rewrites and
redirects must carry both query fields, including an explicit All; remounting
on a default route must not manufacture a new project scope. Contract
consumers import the matching declarations and assets from the same product
revision.
