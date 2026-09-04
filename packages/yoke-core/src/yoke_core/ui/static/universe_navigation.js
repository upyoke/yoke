import {
  NAV,
  NAV_GROUPS,
  SCOPE_MULTI,
  SCOPE_NONE,
  SCOPE_SINGLE,
} from "./universe_destinations.js";

export { NAV, NAV_GROUPS, SCOPE_MULTI, SCOPE_NONE, SCOPE_SINGLE };

export function navEntry(view) {
  return NAV.find((entry) => entry.id === view) || NAV[0];
}

export function universeNavScope(view) {
  return navEntry(view).scope;
}

// `#/<view>[/<detail>][?project=<id>[,<id>…]]`. The query stays raw string
// here — `scopeForEntry` interprets it against the view's declared scope kind
// (a multi view reads a comma-joined set, a single view one id).
//
// The optional second segment is a drill-in: one row of the view, reached from
// that row. There is no tab segment. A tab was one facet of a view's single
// concept, and every facet that earned a name is now a destination with its
// own entry — which is what a facet an operator navigates to actually is.
// A drill-in is still not a destination: it has no entry, and its parent view
// stays the active one.
export function parseUniverseRoute(hash) {
  const raw = String(hash || "").replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const [viewPart, segmentPart] = pathPart.split("/");
  const view = NAV.some((entry) => entry.id === viewPart)
    ? viewPart : NAV[0].id;
  const project = new URLSearchParams(queryPart || "").get("project");
  // An unknown view falls back to the first destination, and its detail
  // segment falls with it rather than being carried onto a view that never
  // asked for one.
  const detail = (view === viewPart && segmentPart)
    ? decodeURIComponent(segmentPart) : null;
  return { view, tab: null, detail, project };
}

export function buildUniverseRoute(
  view,
  project,
  segment = null,
  detail = null,
) {
  const resolvedView = NAV.some((entry) => entry.id === view)
    ? view : NAV[0].id;
  const segmentPart = (resolvedView === view && segment)
    ? `/${encodeURIComponent(segment)}` : "";
  const detailPart = segmentPart && detail
    ? `/${encodeURIComponent(detail)}` : "";
  // Commas separate the members of a project set and stay literal so the
  // route reads the way it was written; everything else percent-encodes.
  const query = project
    ? `?project=${encodeURIComponent(project).replace(/%2C/g, ",")}`
    : "";
  return `#/${resolvedView}${segmentPart}${detailPart}${query}`;
}

export function knownProjectId(projects, candidate) {
  return projects.some((row) => String(row.id) === String(candidate))
    ? String(candidate) : null;
}

// The comma-joined route form as a set of ids the roster knows. Unknown ids
// drop out rather than filtering rows to nothing; an all-unknown or empty
// value reads as no selection at all.
function knownProjectSet(projects, candidate) {
  const members = String(candidate || "").split(",")
    .map((member) => knownProjectId(projects, member.trim()))
    .filter((member, index, all) =>
      member !== null && all.indexOf(member) === index);
  return members.length ? members : null;
}

// What a multi view last held, revalidated against the current roster: a
// remembered set whose projects have all vanished is no selection at all.
function rememberedMultiScope(projects, remembered) {
  if (remembered === "all") return "all";
  if (!Array.isArray(remembered)) return null;
  return knownProjectSet(projects, remembered.join(","));
}

// The route encoding of a resolved scope: absent for "all" (an unfiltered
// universe needs no parameter), comma-joined ids for a set, and a single
// view's project string unchanged.
export function serializeScope(scope) {
  if (scope === null || scope === "all") return null;
  return Array.isArray(scope) ? scope.join(",") : String(scope);
}

// A multi view's scope is the whole universe ("all") or an array of project
// ids; a single view's is one project id. Either way the resolved value is
// stored per view, so each screen remembers its own scope.
export function scopeForEntry(entry, routeProject, projects, selections) {
  if (entry.scope === SCOPE_NONE) return null;
  if (entry.scope === SCOPE_MULTI) {
    const resolved = routeProject === "all"
      ? "all"
      : knownProjectSet(projects, routeProject) ||
        rememberedMultiScope(projects, selections.get(entry.id)) ||
        "all";
    selections.set(entry.id, resolved);
    return resolved;
  }
  const resolved = knownProjectId(projects, routeProject) ||
    knownProjectId(projects, selections.get(entry.id)) ||
    (projects[0] ? String(projects[0].id) : null);
  if (resolved !== null) selections.set(entry.id, resolved);
  return resolved;
}

// What a nav link's href carries for its destination: the scope that view
// last held, serialized — nothing when it holds "all" or was never visited
// (the view resolves its own default on arrival).
export function rememberedScopeParam(entry, projects, selections) {
  if (entry.scope === SCOPE_NONE) return null;
  const remembered = selections.get(entry.id);
  if (entry.scope === SCOPE_MULTI) {
    return serializeScope(rememberedMultiScope(projects, remembered) || "all");
  }
  return knownProjectId(projects, remembered);
}

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// An unbuilt destination says only that it is coming: the page head above
// the stub is the single place a view's name and summary render, so the
// panel repeating either would show the same words twice at two sizes.
// `summary`, when given, is the line saying what this stub will be. A
// destination stub omits it, because the page head above already carries the
// entry's own summary.
export function renderStubView(context, main, summary) {
  const documentNode = context.document;
  const panel = el(documentNode, "section", "stub-panel");
  panel.appendChild(el(documentNode, "span", "badge", "◷ Coming soon"));
  if (summary) {
    panel.appendChild(el(documentNode, "p", "stub-summary", summary));
  }
  // A skeleton of what will stand here — bars, not controls, so nothing
  // pretends to act.
  const preview = el(documentNode, "div", "preview");
  for (const width of ["60%", "", "80%", "40%"]) {
    const bar = el(documentNode, "div", "ln");
    if (width) bar.style.width = width;
    preview.appendChild(bar);
  }
  panel.appendChild(preview);
  main.replaceChildren(panel);
}

// Toggle one project inside a multi view's scope: from "all" the set starts
// empty, so the first click narrows to that one project; removing the last
// member widens back to "all". Members keep roster order so the route
// encoding of the same set is always the same string.
function toggledScope(scope, projectId, projects) {
  const members = new Set(scope === "all" ? [] : scope);
  if (members.has(projectId)) members.delete(projectId);
  else members.add(projectId);
  if (members.size === 0) return "all";
  return projects.map((row) => String(row.id))
    .filter((rosterId) => members.has(rosterId));
}

// The scope control above a live scoped view: a row of chips. A multi view
// gets an "All" chip plus one per project and set-toggle semantics; a single
// view gets one chip per project with radio semantics.
export function createScopePicker(options) {
  const {
    documentNode, entry, scope, projects, renderRoute, scopeSelections,
    segment, windowNode, onScopeChange,
  } = options;
  const multi = entry.scope === SCOPE_MULTI;
  const bar = el(documentNode, "div", "scope-bar");
  bar.appendChild(el(
    documentNode, "span", "scope-label", multi ? "Projects" : "Project",
  ));

  // The picker holds its own live scope so a chip toggle after an external
  // setScope (a held view's in-place rescope) reads the current selection, not
  // the value baked in at build time.
  let currentScope = scope;
  const chips = [];
  const selectedFor = (scopeValue, projectId) => {
    if (projectId === null) return scopeValue === "all";
    return multi
      ? Array.isArray(scopeValue) && scopeValue.includes(projectId)
      : String(scopeValue) === projectId;
  };
  const syncChips = (scopeValue) => {
    for (const { projectId, button } of chips) {
      button.classList.toggle("on", selectedFor(scopeValue, projectId));
    }
  };
  const apply = (next) => {
    currentScope = next;
    syncChips(next);
    scopeSelections.set(entry.id, next);
    // Re-scoping stays where it is: the drill-in segment survives the
    // scope change.
    windowNode.location.hash = buildUniverseRoute(
      entry.id, serializeScope(next), segment || null,
    );
    // A held view repaints in place from its own data; every other view falls
    // back to a full route render (which refetches).
    if (onScopeChange) onScopeChange(next);
    else renderRoute();
  };

  const chip = (label, projectId, onClick) => {
    const button = el(documentNode, "button", "scope-chip", label);
    button.type = "button";
    button.addEventListener("click", onClick);
    chips.push({ projectId, button });
    bar.appendChild(button);
  };

  if (multi) chip("All", null, () => apply("all"));
  for (const row of projects) {
    const projectId = String(row.id);
    chip(row.slug || row.name || projectId, projectId, () => {
      apply(multi ? toggledScope(currentScope, projectId, projects) : projectId);
    });
  }
  syncChips(currentScope);

  // Update the chip highlights to an externally-resolved scope with no route
  // side effect (used by the held-view in-place rescope path).
  bar.setScope = (next) => {
    currentScope = next;
    syncChips(next);
  };
  return bar;
}

