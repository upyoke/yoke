# Project selection in the shared app

The top navigation remembers All, one project, or a set of projects across
every destination, detail page, workflow route, reload, and history entry.
Global screens keep the selection visible and label their content as
universe-wide. A screen needing one project has a separate **Focus project**
control; changing it does not replace the remembered selection.

The mount option `selectionIdentity: { universeId, actorId }` enables browser
storage for one authenticated viewer in one universe. Hosts supply stable IDs,
not names, and unmount/remount when either identity changes. Without a known
identity, preferences remain in memory for that mount. The local server derives
identity from the universe organization birth and the same resolved operator
used for UI actions. No authorization derives from stored preferences or URLs.
All selection and focus IDs are revalidated against the accessible project
roster. A failed roster load preserves saved preferences and asks for a reload.

Routes use `project=all` or comma-separated project IDs for selection on list
and global destinations. On detail and single-project destinations, `project`
addresses the resource/focus and `selection` carries the remembered selection:
`#/strategy/PLAN?project=2&selection=1,2`. An explicit deep-link selection wins;
without `selection`, an explicit `project` initializes selection. An absent
scope preserves the current preference. The shell replaces an incomplete URL
with its resolved scope without adding a history entry, so back/forward can
restore All independently of later changes.

Hosts use the exported `withProjectSelection(hash, selection)` for ordinary
navigation. The shared shell applies it to its own and host-provided anchors
and to renderer navigation callbacks. It preserves explicit selection and
resource project values. Hosted route rewrites and redirects must carry both
query fields, including an explicit All; remounting on a default route must
not manufacture a new project scope. Contract consumers import the matching
declarations and assets from the same product revision.
