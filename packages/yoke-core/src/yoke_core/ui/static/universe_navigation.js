// Stable workbench destinations and their project-scope contracts.

export const SCOPE_MULTI = "multi";
export const SCOPE_SINGLE = "single";
export const SCOPE_NONE = "none";

export const NAV = [
  {
    id: "overview", icon: "⊞", label: "Overview", scope: SCOPE_MULTI,
    summary: "The universe at a glance, across every project.",
  },
  {
    id: "inbox", icon: "✉", label: "Inbox", scope: SCOPE_MULTI,
    summary: "What needs you to know about it or act on it.",
  },
  { id: "strategy", icon: "❖", label: "Strategy", scope: SCOPE_MULTI },
  {
    id: "frontier", icon: "⚡", label: "Frontier", scope: SCOPE_MULTI,
    summary: "What runs next and why, and what a waiting item waits on.",
  },
  { id: "items", icon: "≣", label: "Items", scope: SCOPE_MULTI },
  {
    id: "board", icon: "▦", label: "Board", scope: SCOPE_MULTI,
    summary: "Your .yoke/BOARD.md, as the board itself renders it.",
  },
  {
    id: "sessions", icon: "◈", label: "Sessions", scope: SCOPE_MULTI,
    summary:
      "Each session: who runs it, what it holds, and how alive it is.",
  },
  {
    id: "delivery", icon: "⬈", label: "Delivery", scope: SCOPE_MULTI,
    summary: "Environments, flows and runs, with databases and infrastructure.",
    // Delivery is one concept asked five ways, so its second route segment
    // names a tab rather than a drill-in row.
    tabs: [
      {
        id: "runs", label: "Runs",
        summary: "Each run of a flow against a target environment.",
      },
      {
        id: "environments", label: "Environments",
        summary: "The deploy targets runs ship to.",
      },
      {
        id: "flows", label: "Flows",
        summary: "The pipeline definitions runs execute.",
      },
      {
        id: "databases", label: "Databases",
        summary:
          "Declared database models, their posture, and the apply records.",
      },
      {
        id: "infrastructure", label: "Infrastructure",
        summary:
          "What backs an environment, with drift from the template as the signal.",
      },
    ],
  },
  {
    id: "qa", icon: "◉", label: "QA", scope: SCOPE_MULTI,
    summary: "Quality gates and the evidence they collected.",
  },
  {
    id: "workflows", icon: "⚗", label: "Workflows", scope: SCOPE_SINGLE,
    summary: "What done means for a type of work, and the parts that compose it.",
  },
  {
    id: "capabilities", icon: "⚿", label: "Capabilities", scope: SCOPE_MULTI,
    summary: "What Yoke can reach on your behalf, and when it last verified it.",
  },
  { id: "events", icon: "≋", label: "Events", scope: SCOPE_MULTI },
  {
    id: "doctor", icon: "♥", label: "Doctor", scope: SCOPE_MULTI,
    summary: "The health checks and what they found.",
  },
  { id: "ouroboros", icon: "∞", label: "Ouroboros", scope: SCOPE_MULTI },
  { id: "projects", icon: "▤", label: "Projects", scope: SCOPE_NONE },
  {
    id: "access", icon: "⚇", label: "Access", scope: SCOPE_NONE,
    summary: "Who and what may act here, at the universe and per project.",
  },
  // Host-fed destinations: the workbench routes them and draws their page
  // head, but their body is a host-supplied section, so each entry shows in
  // the nav exactly when the host supplies its content.
  {
    id: "members", icon: "⚉", label: "Members", scope: SCOPE_NONE,
    summary: "The people in your organization, managed by the hosting platform.",
    hostFed: true,
  },
  {
    id: "billing", icon: "❒", label: "Billing", scope: SCOPE_NONE,
    summary: "Your plan and payments, managed by the hosting platform.",
    hostFed: true,
  },
  {
    id: "templates", icon: "◫", label: "Templates", scope: SCOPE_NONE,
    summary: "The templates projects are rendered from.",
  },
  {
    id: "github", icon: "⎇", label: "GitHub", scope: SCOPE_SINGLE,
    summary: "How this project binds to its repository, and how they sync.",
  },
  {
    id: "project-settings", icon: "⚙", label: "Project settings", scope: SCOPE_SINGLE,
    summary: "Settings for one project.",
  },
  {
    id: "universe-settings", icon: "⛭", label: "Universe settings", scope: SCOPE_NONE,
    summary: "Settings for this universe, including export and import.",
  },
];

export function navEntry(view) {
  return NAV.find((entry) => entry.id === view) || NAV[0];
}

export function universeNavScope(view) {
  return navEntry(view).scope;
}

// `#/<view>[/<segment>][?project=<id>[,<id>…]]`. The query value stays a raw
// string here — `scopeForEntry` interprets it against the view's declared
// scope kind (a multi view reads a comma-joined set, a single view one id).
// The optional second segment belongs to the view, and each view declares
// what it means — one meaning, never both:
//  * a view with a `tabs` roster reads it as a tab: one facet of the view's
//    single concept. An absent or unknown segment resolves to the first tab,
//    so `#/delivery` lands on the default facet without a hash rewrite.
//  * every other view reads it as a drill-in: one row of the view, reached
//    from that row and carrying a breadcrumb back.
// Neither a tab nor a drill-in is a nav destination of its own — it has no
// entry, and its parent view stays the active one.
export function parseUniverseRoute(hash) {
  const raw = String(hash || "").replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const [viewPart, segmentPart] = pathPart.split("/");
  const view = NAV.some((entry) => entry.id === viewPart)
    ? viewPart : NAV[0].id;
  const project = new URLSearchParams(queryPart || "").get("project");
  const tabs = navEntry(view).tabs;
  if (tabs) {
    // Tab ids are plain words, so the raw segment compares directly; an
    // encoded or unknown one simply resolves to the default facet.
    const tab = tabs.some((item) => item.id === segmentPart)
      ? segmentPart : tabs[0].id;
    return { view, tab, detail: null, project };
  }
  // An unknown view falls back to the first destination, and its detail
  // segment falls with it rather than being carried onto a view that never
  // asked for one.
  const detail = (view === viewPart && segmentPart)
    ? decodeURIComponent(segmentPart) : null;
  return { view, tab: null, detail, project };
}

export function buildUniverseRoute(view, project, segment = null) {
  const resolvedView = NAV.some((entry) => entry.id === view)
    ? view : NAV[0].id;
  const segmentPart = (resolvedView === view && segment)
    ? `/${encodeURIComponent(segment)}` : "";
  // Commas separate the members of a project set and stay literal so the
  // route reads the way it was written; everything else percent-encodes.
  const query = project
    ? `?project=${encodeURIComponent(project).replace(/%2C/g, ",")}`
    : "";
  return `#/${resolvedView}${segmentPart}${query}`;
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
    const resolved = knownProjectSet(projects, routeProject) ||
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
    chip(row.name || row.slug || projectId, selected, () => {
      apply(multi ? toggledScope(scope, projectId, projects) : projectId);
    });
  }

  bar.appendChild(el(
    documentNode, "span", "scope-hint",
    multi
      ? "all / one / some · this screen remembers its own"
      : "one project — this screen configures a single target",
  ));
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
