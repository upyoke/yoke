import {
  NAV,
  SCOPE_MULTI,
  SCOPE_NONE,
  SCOPE_SINGLE,
} from "./universe_destinations.js";

export { NAV, SCOPE_MULTI, SCOPE_NONE, SCOPE_SINGLE };

export function navEntry(view) {
  return NAV.find((entry) => entry.id === view) || NAV[0];
}

export function universeNavScope(view) {
  return navEntry(view).scope;
}

// `#/<view>[/<segment>[/<detail>]][?project=<id>[,<id>…]]`. The query stays raw
// string here — `scopeForEntry` interprets it against the view's declared
// scope kind (a multi view reads a comma-joined set, a single view one id).
// The optional second segment belongs to the view, and each view declares
// what it means:
//  * a view with a `tabs` roster reads it as a tab: one facet of the view's
//    single concept. A tab may use the third segment for one of its own
//    durable drill-ins, so `#/qa/methods/browser-check` is shareable without
//    turning a method into a top-level destination.
//  * every other view reads it as a drill-in: one row of the view, reached
//    from that row.
// Neither a tab nor a drill-in is a nav destination of its own — it has no
// entry, and its parent view stays the active one.
export function parseUniverseRoute(hash) {
  const raw = String(hash || "").replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const [viewPart, segmentPart, detailPart] = pathPart.split("/");
  const view = NAV.some((entry) => entry.id === viewPart)
    ? viewPart : NAV[0].id;
  const project = new URLSearchParams(queryPart || "").get("project");
  const tabs = navEntry(view).tabs;
  if (tabs) {
    // Tab ids are plain words, so the raw segment compares directly; an
    // encoded or unknown one simply resolves to the default facet.
    const tab = tabs.some((item) => item.id === segmentPart)
      ? segmentPart : tabs[0].id;
    const detail = (
      view === viewPart
      && tab === segmentPart
      && detailPart
    ) ? decodeURIComponent(detailPart) : null;
    return { view, tab, detail, project };
  }
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
// destination stub omits it — the page head above already carries the
// entry's own summary — but a tab stub must state its facet here, because
// the page head names the view, not the facet.
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
    segment, windowNode,
  } = options;
  const multi = entry.scope === SCOPE_MULTI;
  const bar = el(documentNode, "div", "scope-bar");
  bar.appendChild(el(
    documentNode, "span", "scope-label", multi ? "Projects" : "Project",
  ));

  const apply = (next) => {
    scopeSelections.set(entry.id, next);
    // Re-scoping stays on the same facet: the segment (a tab, when the
    // view declares tabs) survives the scope change.
    windowNode.location.hash = buildUniverseRoute(
      entry.id, serializeScope(next), segment || null,
    );
    renderRoute();
  };

  const chip = (label, selected, onClick) => {
    const button = el(documentNode, "button", "scope-chip", label);
    button.type = "button";
    button.classList.toggle("on", selected);
    button.addEventListener("click", onClick);
    bar.appendChild(button);
  };

  if (multi) chip("All", scope === "all", () => apply("all"));
  for (const row of projects) {
    const projectId = String(row.id);
    const selected = multi
      ? Array.isArray(scope) && scope.includes(projectId)
      : String(scope) === projectId;
    chip(row.slug || row.name || projectId, selected, () => {
      apply(multi ? toggledScope(scope, projectId, projects) : projectId);
    });
  }

  return bar;
}

// The facet strip under a tabbed view's chrome: real links, so a tab is
// shareable and middle-clickable like any route. Each link carries the
// view's project so switching facets keeps the scope.
export function createTabBar(documentNode, entry, activeTabId, project) {
  const bar = el(documentNode, "div", "tab-bar");
  for (const tab of entry.tabs) {
    const link = el(documentNode, "a", "tab-link", tab.label);
    link.href = buildUniverseRoute(entry.id, project, tab.id);
    link.classList.toggle("active", tab.id === activeTabId);
    bar.appendChild(link);
  }
  return bar;
}
