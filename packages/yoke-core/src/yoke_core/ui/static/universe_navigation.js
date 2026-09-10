import {
  NAV,
  NAV_GROUPS,
  SCOPE_MULTI,
  SCOPE_NONE,
  SCOPE_SINGLE,
} from "./universe_destinations.js";
import {
  knownProjectId, resolveProjectSelection, selectionParam,
} from "./universe_project_selection.js";
export { knownProjectId } from "./universe_project_selection.js";

export { NAV, NAV_GROUPS, SCOPE_MULTI, SCOPE_NONE, SCOPE_SINGLE };

export function navEntry(view) {
  return NAV.find((entry) => entry.id === view) || NAV[0];
}

export function universeNavScope(view) {
  return navEntry(view).scope;
}

// Project carries list selection or resource focus; selection separates the
// remembered scope from detail/focus when both must travel in one URL.
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
  const query = new URLSearchParams(queryPart || "");
  const project = query.get("project");
  const selection = query.get("selection");
  // An unknown view falls back to the first destination, and its detail
  // segment falls with it rather than being carried onto a view that never
  // asked for one.
  const detail = (view === viewPart && segmentPart)
    ? decodeURIComponent(segmentPart) : null;
  return { view, tab: null, detail, project, selection };
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

// The route encoding of a resolved scope: absent for "all" (an unfiltered
// universe needs no parameter), comma-joined ids for a set, and a single
// view's project string unchanged.
export function serializeScope(scope) {
  if (scope === null || scope === "all") return null;
  return Array.isArray(scope) ? scope.join(",") : String(scope);
}

export function scopeForEntry(entry, routeProject, projects, selections, routeSelection = null) {
  const selection = resolveProjectSelection(selections, entry.id, projects, routeSelection ?? routeProject);
  if (entry.scope === SCOPE_NONE) return null;
  if (entry.scope === SCOPE_MULTI) return selection;
  const candidates = selection === "all" ? projects.map((row) => String(row.id)) : selection;
  const priorFocus = selections.focusFor(entry.id);
  const focus = knownProjectId(projects, routeProject) ||
    priorFocus || candidates[0] || null;
  selections.setFocusFor(entry.id, focus);
  if (focus !== priorFocus) selections.saveFor(entry.id);
  return focus;
}

// Each destination carries its OWN remembered selection, including global
// screens — never another screen's.
export function rememberedScopeParam(entry, projects, selections) {
  return selectionParam(selections.selectionFor(entry.id));
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
    documentNode, entry, scope, projects, onSelect,
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
    onSelect(next);
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
    chip(row.public_item_prefix || projectId, projectId, () => {
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
