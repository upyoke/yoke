# Project selection in the shared app

Project pickers and project inventories show active projects by default.
Retire a disposable project with `yoke projects retire --project P --reason TEXT`;
complete open items and deployment runs and release held claims before retrying
a refusal. Retirement preserves all history. `yoke projects unretire --project P`
restores visibility, and `yoke projects list --include-retired` includes historical
projects. Direct reads by slug or id continue to resolve retired projects.

The top navigation remembers All, one project, or a set of projects
**independently for each destination** — Strategy, Frontier, Shipping,
Sessions, Inbox, and every other screen each keep their own selection across
navigation, reload, and a second tab. Changing one screen's selection never rewrites another's. Universe-wide
screens hide the selector because it does not filter their content.
A screen needing one project has a separate **Focus project** control;
changing it does not replace the remembered selection. Architecture and Ouroboros
use this single-project pattern: their content picker offers one project at a
time, and Ouroboros requests name that project explicitly. Old All or multiple-
project URLs resolve to the remembered focus, or the first accessible project.

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

The same preference pair remembers the actor's last dashboard location,
including its query string. The list response carries `last_location`; a
navigation sends `view_id` and `location` in the set payload. A set payload
with `location` writes only the location, leaving selection and focus untouched.
It is stored under `screen.location.last` in
`actor_ui_preferences`, independently of `screen.selection.<view id>`.
Signing back in or opening a bare dashboard entry restores that location
before the first page renders. An explicit path route always wins and
becomes the remembered location, including an explicit default screen.
Restoration checks the accessible project roster and the detail's current
resource authority; unknown, removed, or inaccessible locations silently
open the default destination. A navigation during restoration wins over
the saved route. Writes are serialized and repeated renders of the same
location do not write again. Failed preference reads leave persistence off
for that mount. Last-page saves are a silent background convenience: a failed
save never adds a notice to the header or project picker. It logs the server's
error code and HTTP status to the console; a transport failure logs
`location_save_network_failed`. Hosted saves strip the dashboard base path
and persist a path route such as `/sessions?project=all`, without a fragment.
An older serving build that omits `last_location` retains the usual default
entry behavior until the updated server is deployed.

**All and "every project" are one scope, in one form.** A member list covering
the whole roster is resolved, stored, routed and rendered as All — the All chip
lights and no project chip does. Two forms of that scope let the stored value,
the route and the chip row disagree: the All chip stays dark, and the chip row
turns subtractive, so clicking a project removes it instead of narrowing to it
and the selector keeps landing back on every chip selected. The comparison is
against the live accessible roster, never a fixed count, so it holds for any
universe. A roster of one is left alone: its single chip already toggles
cleanly between All and that project, and collapsing it would make the chip
inert and widen that universe's scoped reads to unfiltered.

Routes use `project=all` or comma-separated project IDs for selection on list
and global destinations. On detail and single-project destinations, `project`
addresses the resource/focus and `selection` carries the remembered selection:
`/strategy/PLAN?project=2&selection=1,2`. An explicit deep-link selection wins;
without `selection`, an explicit `project` initializes selection. An absent
scope preserves that destination's current preference. The shell replaces an
incomplete URL with its resolved scope without adding a history entry, so
back/forward can restore All independently of later changes.

Hosts use the exported `withProjectSelection(href, selections, basePath)` for ordinary
navigation, where `selections` is the shared per-screen state object; it looks
up the TARGET route's own view to decide what to carry, never the currently
active screen's value. The shared shell applies it to its own and
host-provided anchors and to renderer navigation callbacks. It preserves
explicit selection and resource project values. Hosted route rewrites and
redirects must carry both query fields, including an explicit All; remounting
on a default route must not manufacture a new project scope. Contract
consumers import the matching declarations and assets from the same product
revision.


## Creating items

New Item hides the top-navigation project filter. Its labeled Project dropdown
in the form selects the creation target independently of the Items list scope.
All or a multi-project scope opens an explicit choice when several projects
are available. `projects.list` with `for_item_creation: true` returns only
projects authorized for `items.write`, with `creation_scoped: true` attesting
that filtering. A server without that projection is named as unavailable;
creation requires updating it. Project changes preserve title and instruction,
refresh workflows, the title limit, QA choices and execution instructions, and
reset optional settings for review. Cancel returns to the remembered Items scope.

## Items ordering

Items defaults to Last updated descending. Each column header toggles ascending
and descending ordering, and announces its direction through `aria-sort`.
`items.overview.list` takes `sort_column` and `sort_direction` alongside
`page_size`; ordering applies to the full filtered set before keyset paging.
Cursors bind their stored sort value and item id to the chosen column and
direction. A mismatched cursor refuses with a reload instruction. IDs order
by project prefix and numeric sequence. Last updated uses the shared relative
time control, with the exact time accessible by hover, click or keyboard.

The existing `ui_preferences.screen_selection.list` returns `sorts` alongside
project selections and location. A set request with `view_id: "items"` and
`sort: {column, direction}` writes only `screen.sort.items` in the same
actor-scoped store; it never rewrites project selection, focus or location.
Sort writes are serialized so rapid changes settle in the chosen order.
Initial preference-read failures disable persistence until reload, and a
failed sort save reports how to retry on the Items page.
