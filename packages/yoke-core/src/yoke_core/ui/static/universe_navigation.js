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
    summary: "Each running session: its execution lane and its mode.",
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

// `#/<view>[/<segment>][?project=<id>]`. The optional second segment belongs
// to the view, and each view declares what it means — one meaning, never
// both:
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
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  return `#/${resolvedView}${segmentPart}${query}`;
}

export function knownProjectId(projects, candidate) {
  return projects.some((row) => String(row.id) === String(candidate))
    ? String(candidate) : null;
}

export function scopeForEntry(entry, routeProject, projects, selections) {
  if (entry.scope === SCOPE_NONE) return null;
  const resolved = knownProjectId(projects, routeProject) ||
    knownProjectId(projects, selections.get(entry.id)) ||
    (projects[0] ? String(projects[0].id) : null);
  if (resolved !== null) selections.set(entry.id, resolved);
  return resolved;
}

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderStubView(context, main, entry) {
  const documentNode = context.document;
  const panel = el(documentNode, "section", "stub-panel");
  panel.appendChild(el(documentNode, "span", "badge", "◷ Coming soon"));
  panel.appendChild(el(documentNode, "h2", null, entry.label));
  if (entry.summary) {
    panel.appendChild(el(documentNode, "p", "stub-summary", entry.summary));
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

export function createScopePicker(options) {
  const {
    documentNode, entry, project, projects, renderRoute, scopeSelections,
    segment, windowNode,
  } = options;
  const bar = el(documentNode, "div", "scope-bar");
  const picker = el(documentNode, "select", "project-chooser");
  picker.setAttribute("aria-label", "Project");
  for (const row of projects) {
    const option = el(
      documentNode, "option", null,
      row.name || row.slug || String(row.id),
    );
    option.value = String(row.id);
    picker.appendChild(option);
  }
  picker.value = project;
  picker.addEventListener("change", () => {
    scopeSelections.set(entry.id, picker.value);
    // Re-scoping stays on the same facet: the segment (a tab, when the
    // view declares tabs) survives the project change.
    windowNode.location.hash = buildUniverseRoute(
      entry.id, picker.value, segment || null,
    );
    renderRoute();
  });
  bar.appendChild(picker);
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
