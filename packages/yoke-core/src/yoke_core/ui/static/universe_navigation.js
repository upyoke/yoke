// Stable workbench destinations and their project-scope contracts.

export const SCOPE_MULTI = "multi";
export const SCOPE_SINGLE = "single";
export const SCOPE_NONE = "none";

export const NAV = [
  {
    id: "overview", label: "Overview", scope: SCOPE_MULTI,
    summary: "The universe at a glance, across every project.",
  },
  {
    id: "inbox", label: "Inbox", scope: SCOPE_MULTI,
    summary: "What needs you to know about it or act on it.",
  },
  { id: "strategy", label: "Strategy", scope: SCOPE_MULTI },
  {
    id: "frontier", label: "Frontier", scope: SCOPE_MULTI,
    summary: "What runs next and why, and what a waiting item waits on.",
  },
  { id: "items", label: "Items", scope: SCOPE_MULTI },
  {
    id: "board", label: "Board", scope: SCOPE_MULTI,
    summary: "Your .yoke/BOARD.md, as the board itself renders it.",
  },
  {
    id: "sessions", label: "Sessions", scope: SCOPE_MULTI,
    summary: "Each running session: its execution lane and its mode.",
  },
  {
    id: "delivery", label: "Delivery", scope: SCOPE_MULTI,
    summary: "Environments, flows and runs, with databases and infrastructure.",
  },
  {
    id: "qa", label: "QA", scope: SCOPE_MULTI,
    summary: "Quality gates and the evidence they collected.",
  },
  {
    id: "workflows", label: "Workflows", scope: SCOPE_SINGLE,
    summary: "What done means for a type of work, and the parts that compose it.",
  },
  {
    id: "capabilities", label: "Capabilities", scope: SCOPE_MULTI,
    summary: "What Yoke can reach on your behalf, and when it last verified it.",
  },
  { id: "events", label: "Events", scope: SCOPE_MULTI },
  {
    id: "doctor", label: "Doctor", scope: SCOPE_MULTI,
    summary: "The health checks and what they found.",
  },
  {
    id: "ouroboros", label: "Ouroboros", scope: SCOPE_MULTI,
    summary: "What the system noticed about itself and what came of it.",
  },
  { id: "projects", label: "Projects", scope: SCOPE_NONE },
  {
    id: "access", label: "Access", scope: SCOPE_NONE,
    summary: "Who and what may act here, at the universe and per project.",
  },
  {
    id: "templates", label: "Templates", scope: SCOPE_NONE,
    summary: "The templates projects are rendered from.",
  },
  {
    id: "github", label: "GitHub", scope: SCOPE_SINGLE,
    summary: "How this project binds to its repository, and how they sync.",
  },
  {
    id: "project-settings", label: "Project settings", scope: SCOPE_SINGLE,
    summary: "Settings for one project.",
  },
  {
    id: "universe-settings", label: "Universe settings", scope: SCOPE_NONE,
    summary: "Settings for this universe, including export and import.",
  },
];

export function navEntry(view) {
  return NAV.find((entry) => entry.id === view) || NAV[0];
}

export function universeNavScope(view) {
  return navEntry(view).scope;
}

export function parseUniverseRoute(hash) {
  const raw = String(hash || "").replace(/^#\/?/, "");
  const [viewPart, queryPart] = raw.split("?");
  const view = NAV.some((entry) => entry.id === viewPart)
    ? viewPart : NAV[0].id;
  const project = new URLSearchParams(queryPart || "").get("project");
  return { view, project };
}

export function buildUniverseRoute(view, project) {
  const resolvedView = NAV.some((entry) => entry.id === view)
    ? view : NAV[0].id;
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  return `#/${resolvedView}${query}`;
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
  const panel = el(context.document, "section", "panel");
  const header = el(context.document, "div", "panel-header");
  header.appendChild(el(context.document, "h2", null, entry.label));
  panel.appendChild(header);
  const body = el(context.document, "div", "panel-body");
  body.appendChild(el(context.document, "p", "stub-headline", "Coming soon"));
  body.appendChild(el(context.document, "p", "stub-summary", entry.summary));
  panel.appendChild(body);
  main.replaceChildren(panel);
}

export function createScopePicker(options) {
  const {
    documentNode, entry, project, projects, renderRoute, scopeSelections,
    windowNode,
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
    windowNode.location.hash = buildUniverseRoute(entry.id, picker.value);
    renderRoute();
  });
  bar.appendChild(picker);
  return bar;
}
