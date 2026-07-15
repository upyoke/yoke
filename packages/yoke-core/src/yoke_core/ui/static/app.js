// Read-only universe view. Hand-authored vanilla JS: no build step and no
// framework. Everything ships inside the yoke-core wheel.
//
// Mount contract: `mountUniverseApp(rootNode, options?)` renders into a
// host-owned node. The default options preserve `yoke ui`: same-origin
// cookie-authenticated calls to /api/functions/call and no outer slots.
// Another same-realm host may inject its own function client, opaque generic
// capabilities/actions, and named slot nodes without forking this app.
//
// Views are hash-routed as `#/<view>?project=<id>` so a shared link restores
// both the view and the scope. The left nav is data-driven (see NAV) — adding
// a route is one more array entry, with no per-view branching in the markup.
//
// Scope is per-screen: each view remembers its own project and declares how it
// takes scope (see SCOPE_*). Live scoped views carry their own picker; stubs do
// not render a control that cannot act.
//
// Members and Billing are deliberately absent from NAV. They are hosted
// chrome the platform injects through the `navigationEnd` slot; the workbench
// itself has no notion of an account.

import {
  UNIVERSE_APP_CONTRACT_VERSION,
  createHttpFunctionClient,
} from "./contract.js";
import {
  appendSlot, attachMountRootClass,
  createUnmountHandle, detachMountedSlots, materializeSlots,
  renderCapabilityActions,
  validateMountRoot,
} from "./mount-options.js";

export {
  UNIVERSE_APP_CONTRACT_VERSION,
  createHttpFunctionClient,
} from "./contract.js";

const WORDMARK_ASSET_URL = new URL("./yoke-wordmark.svg", import.meta.url);

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function callFunction(client, functionId, payload, target) {
  const request = { function: functionId, payload: payload || {} };
  // Preserve the local proxy envelope: omit target unless a view supplies
  // one, so global-target reads keep their server-side default.
  if (target) request.target = target;
  return client.call(request);
}

// One titled section with a raw-JSON toggle showing the exact function-call
// response envelope the section rendered from.
function section(documentNode, title) {
  const wrap = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, title));
  const toggle = el(documentNode, "button", "raw-toggle", "raw JSON");
  toggle.type = "button";
  header.appendChild(toggle);
  wrap.appendChild(header);

  const body = el(documentNode, "div", "panel-body", "loading…");
  wrap.appendChild(body);

  const raw = el(documentNode, "pre", "raw-json");
  raw.hidden = true;
  wrap.appendChild(raw);
  toggle.addEventListener("click", () => { raw.hidden = !raw.hidden; });

  wrap.renderEnvelope = (call_result, renderBody) => {
    raw.textContent = JSON.stringify(call_result.envelope, null, 2);
    body.replaceChildren();
    renderBody(body, call_result);
  };
  return wrap;
}

function renderError(body, callResult) {
  const envelope = callResult.envelope || {};
  const detail = (envelope.error && envelope.error.message) ||
    "request failed";
  body.appendChild(el(
    body.ownerDocument, "p", "error",
    `read failed (HTTP ${callResult.status}): ${detail}`,
  ));
}

// Render `rows` as a table whose `columns` each name a header label and a
// per-row cell accessor. Empty rows render the view's own empty message.
function renderTable(body, rows, columns, emptyText) {
  const documentNode = body.ownerDocument;
  if (rows.length === 0) {
    body.appendChild(el(documentNode, "p", "empty", emptyText));
    return;
  }
  const table = el(documentNode, "table", "items");
  const head = el(documentNode, "tr");
  for (const column of columns) {
    head.appendChild(el(documentNode, "th", null, column.label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    for (const column of columns) {
      tr.appendChild(el(
        documentNode, "td", null, String(column.value(row) ?? ""),
      ));
    }
    table.appendChild(tr);
  }
  body.appendChild(table);
}

async function loadSection(
  context, panel, functionId, payload, renderBody, target,
) {
  let callResult;
  try {
    callResult = await callFunction(
      context.client, functionId, payload, target,
    );
  } catch (fetchError) {
    // Network-level failure (server gone, connection refused): status 0
    // marks "no HTTP response" and the panel shows the failure instead
    // of sticking at "loading…".
    callResult = {
      status: 0,
      envelope: { success: false, error: { message: String(fetchError) } },
    };
  }
  if (!context.isMounted()) return;
  const ok = callResult.status === 200 && callResult.envelope.success;
  panel.renderEnvelope(callResult, ok ? renderBody : renderError);
}

function renderItemsView(context, main, projectId) {
  const panel = section(context.document, "Items");
  main.replaceChildren(panel);
  loadSection(
    context, panel,
    "items.list.run",
    { fields: ["id", "title", "status"], project: String(projectId) },
    (body, callResult) => {
      const rows = (callResult.envelope.result || {}).rows || [];
      renderTable(body, rows, [
        { label: "id", value: (row) => row.id },
        { label: "title", value: (row) => row.title },
        { label: "status", value: (row) => row.status },
      ], "no items yet");
    },
  );
}

function renderStrategyView(context, main, projectId) {
  const panel = section(context.document, "Strategy");
  main.replaceChildren(panel);
  loadSection(
    context, panel,
    "strategy.doc.list",
    {},
    (body, callResult) => {
      const docs = (callResult.envelope.result || {}).docs || [];
      renderTable(body, docs, [
        { label: "slug", value: (doc) => doc.slug },
        { label: "title", value: (doc) => doc.title },
        { label: "status", value: (doc) => (doc.archived ? "archived" : "active") },
      ], "no strategy docs yet");
    },
    // Strategy docs are project-scoped through the target, not the payload.
    { kind: "global", project_id: String(projectId) },
  );
}

// MULTI views narrow cross-project rows; SINGLE views bind to one project;
// NONE views describe the registry or universe itself.
const SCOPE_MULTI = "multi";
const SCOPE_SINGLE = "single";
const SCOPE_NONE = "none";

// Ordered work arc. Entries with `render` are live; the others keep their
// stable route and show `summary` under `Coming soon`.
const NAV = [
  {
    id: "overview", label: "Overview", scope: SCOPE_MULTI,
    summary: "The universe at a glance, across every project.",
  },
  {
    id: "inbox", label: "Inbox", scope: SCOPE_MULTI,
    summary: "What needs you to know about it or act on it.",
  },
  {
    id: "strategy", label: "Strategy", scope: SCOPE_MULTI,
    render: renderStrategyView,
  },
  {
    id: "frontier", label: "Frontier", scope: SCOPE_MULTI,
    summary: "What runs next and why, and what a waiting item waits on.",
  },
  { id: "items", label: "Items", scope: SCOPE_MULTI, render: renderItemsView },
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
  {
    id: "events", label: "Events", scope: SCOPE_MULTI,
    summary: "What happened, in the order it happened.",
  },
  {
    id: "doctor", label: "Doctor", scope: SCOPE_MULTI,
    summary: "The health checks and what they found.",
  },
  {
    id: "ouroboros", label: "Ouroboros", scope: SCOPE_MULTI,
    summary: "What the system noticed about itself and what came of it.",
  },
  {
    id: "projects", label: "Projects", scope: SCOPE_NONE,
    summary: "Every project in this universe.",
  },
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

function navEntry(view) {
  return NAV.find((entry) => entry.id === view) || NAV[0];
}

export function universeNavScope(view) {
  return navEntry(view).scope;
}

// A stub states what the screen will be without exposing inert controls.
function renderStubView(context, main, entry) {
  const documentNode = context.document;
  const panel = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, entry.label));
  panel.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  body.appendChild(el(documentNode, "p", "stub-headline", "Coming soon"));
  body.appendChild(el(documentNode, "p", "stub-summary", entry.summary));
  panel.appendChild(body);
  main.replaceChildren(panel);
}

export function parseUniverseRoute(hash) {
  // "#/items?project=3" -> { view: "items", project: "3" }.
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

function emptyUniversePanel(documentNode) {
  const panel = section(documentNode, "Universe");
  panel.renderEnvelope(
    { status: 200, envelope: { success: true, result: {} } },
    (body) => {
      body.appendChild(el(
        documentNode, "p", "empty", "no projects yet",
      ));
    },
  );
  return panel;
}

export function mountUniverseApp(rootNode, options = {}) {
  validateMountRoot(rootNode);
  const documentNode = rootNode.ownerDocument;
  const windowNode = documentNode && documentNode.defaultView;
  if (!documentNode || !windowNode) {
    throw new TypeError("mountUniverseApp root must belong to a window");
  }
  const client = options.client || createHttpFunctionClient();
  if (!client || typeof client.call !== "function") {
    throw new TypeError("mountUniverseApp client must expose call(request)");
  }
  const capabilities = options.capabilities || {};
  const slots = options.slots || {};
  const resolvedSlots = materializeSlots(slots, rootNode);
  const mountedSlotNodes = [];
  let mounted = true;
  const context = {
    client,
    document: documentNode,
    isMounted: () => mounted,
  };

  const brand = el(documentNode, "div", "brand");
  brand.style.color = "var(--yoke-ink)";
  const orgContext = el(documentNode, "span", "org-context", "…");
  const contextSide = el(documentNode, "div", "context-side");
  const capabilityActions = renderCapabilityActions(
    documentNode, capabilities,
  );
  if (capabilityActions) contextSide.appendChild(capabilityActions);
  contextSide.appendChild(orgContext);
  const header = el(documentNode, "header", "topbar");
  appendSlot(header, resolvedSlots.topbarStart, mountedSlotNodes);
  header.appendChild(brand);
  header.appendChild(contextSide);
  appendSlot(header, resolvedSlots.topbarEnd, mountedSlotNodes);

  const navEl = el(documentNode, "nav", "sidenav");
  const main = el(documentNode, "main", "content");
  const shell = el(documentNode, "div", "shell");
  appendSlot(navEl, resolvedSlots.navigationStart, mountedSlotNodes);
  shell.appendChild(navEl);
  appendSlot(shell, resolvedSlots.contentBefore, mountedSlotNodes);
  shell.appendChild(main);
  appendSlot(shell, resolvedSlots.contentAfter, mountedSlotNodes);

  const navLinks = new Map();
  for (const entry of NAV) {
    const link = el(documentNode, "a", "nav-link", entry.label);
    navLinks.set(entry.id, link);
    navEl.appendChild(link);
  }
  appendSlot(navEl, resolvedSlots.navigationEnd, mountedSlotNodes);

  const detachRootClass = attachMountRootClass(rootNode);
  rootNode.replaceChildren(header, shell);

  // The mark uses currentColor, so it must live in the DOM (an <img src>
  // would not inherit color); the brand container's ink flips in dark mode.
  Promise.resolve().then(() => globalThis.fetch(WORDMARK_ASSET_URL))
    .then((response) => response.text())
    .then((svg) => { if (mounted) brand.innerHTML = svg; })
    .catch(() => { if (mounted) brand.textContent = "Yoke"; });

  Promise.resolve().then(() => callFunction(client, "organizations.get", {}))
    .then((callResult) => {
      if (!mounted) return;
      const org = (callResult.envelope && callResult.envelope.result) || {};
      orgContext.textContent = org.name || "(unnamed org)";
    })
    .catch(() => { if (mounted) orgContext.textContent = ""; });

  let projects = [];
  // Each visited scoped view remembers its own project.
  const scopeSelections = new Map();

  function defaultProject() {
    return projects[0] ? String(projects[0].id) : null;
  }

  function knownProject(candidate) {
    return projects.some((row) => String(row.id) === String(candidate))
      ? String(candidate) : null;
  }

  // The hash wins when it names a project this universe has, because a shared
  // link must land where it says. Otherwise the view falls back to what it was
  // last left on, then to the first project.
  function scopeFor(entry, routeProject) {
    if (entry.scope === SCOPE_NONE) return null;
    const resolved = knownProject(routeProject) ||
      knownProject(scopeSelections.get(entry.id)) || defaultProject();
    if (resolved !== null) scopeSelections.set(entry.id, resolved);
    return resolved;
  }

  function createScopePicker(entry, project) {
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
      // A same-view scope change rewrites the query, and an unchanged view
      // means no hashchange fires; render directly so the rows follow the
      // picker rather than the heading moving alone.
      renderRoute();
    });
    bar.appendChild(picker);
    return bar;
  }

  function renderRoute() {
    const route = parseUniverseRoute(windowNode.location.hash);
    const entry = navEntry(route.view);
    const project = scopeFor(entry, route.project);

    for (const navItem of NAV) {
      const link = navLinks.get(navItem.id);
      link.href = buildUniverseRoute(
        navItem.id,
        navItem.scope === SCOPE_NONE
          ? null
          : (knownProject(scopeSelections.get(navItem.id)) || project),
      );
      link.classList.toggle("active", navItem.id === entry.id);
    }

    if (!entry.render) {
      renderStubView(context, main, entry);
      return;
    }
    if (entry.scope === SCOPE_NONE) {
      entry.render(context, main, null);
      return;
    }
    if (project === null) {
      main.replaceChildren(emptyUniversePanel(documentNode));
      return;
    }
    // The picker is the view's own chrome, so it sits in the content column
    // above a host the view owns outright and re-renders into at will.
    const viewHost = el(documentNode, "div", "view-host");
    main.replaceChildren(createScopePicker(entry, project), viewHost);
    entry.render(context, viewHost, project);
  }

  windowNode.addEventListener("hashchange", renderRoute);

  Promise.resolve().then(() => callFunction(
    client, "projects.list", { fields: ["id", "slug", "name"] },
  ))
    .then((callResult) => {
      const result = (callResult.envelope && callResult.envelope.result) || {};
      projects = result.rows || [];
    })
    // A roster that fails to load leaves the universe empty. The catch stays
    // on the fetch alone: folding the first render into it would report any
    // view's render error as "no projects yet".
    .catch(() => { projects = []; })
    .then(() => { if (mounted) renderRoute(); });

  return createUnmountHandle(UNIVERSE_APP_CONTRACT_VERSION, () => {
    mounted = false;
    windowNode.removeEventListener("hashchange", renderRoute);
    detachMountedSlots(rootNode, mountedSlotNodes);
    rootNode.replaceChildren();
    detachRootClass();
  });
}
