// Read-only universe view. Hand-authored vanilla JS: no build step and no
// framework. Everything ships inside the yoke-core wheel.
//
// Mount contract: `mountUniverseApp(rootNode, options?)` renders into a
// host-owned node. The default options preserve `yoke ui`: same-origin
// cookie-authenticated calls to /api/functions/call and no outer slots.
// Another same-realm host may inject its own function client, opaque generic
// capabilities/actions, and named slot nodes without forking this app.
//
// Two views, hash-routed: `#/items` and `#/strategy`, each carrying the
// selected project as `?project=<id>` so a shared link restores both the
// view and the scope. The left nav is data-driven (see NAV) — adding a
// route is one more array entry, with no per-view branching in the markup.

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

// The nav roster. Each entry renders one view into <main>; the markup maps
// over this array, so a future {id:"runs",...} is a one-line addition.
const NAV = [
  { id: "items", label: "Items", render: renderItemsView },
  { id: "strategy", label: "Strategy", render: renderStrategyView },
];

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
  const chooser = el(documentNode, "select", "project-chooser");
  const orgContext = el(documentNode, "span", "org-context", "…");
  const contextSide = el(documentNode, "div", "context-side");
  const capabilityActions = renderCapabilityActions(
    documentNode, capabilities,
  );
  if (capabilityActions) contextSide.appendChild(capabilityActions);
  contextSide.appendChild(chooser);
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

  function resolveRoute() {
    const { view, project } = parseUniverseRoute(windowNode.location.hash);
    const known = projects.some((row) => String(row.id) === String(project));
    const resolved = known
      ? project
      : (projects[0] ? String(projects[0].id) : null);
    return { view, project: resolved };
  }

  function renderRoute() {
    const { view, project } = resolveRoute();
    if (chooser.value !== (project || "")) chooser.value = project || "";
    for (const entry of NAV) {
      const link = navLinks.get(entry.id);
      link.href = buildUniverseRoute(entry.id, project);
      link.classList.toggle("active", entry.id === view);
    }
    if (project === null) {
      main.replaceChildren(emptyUniversePanel(documentNode));
      return;
    }
    (NAV.find((entry) => entry.id === view) || NAV[0]).render(
      context, main, project,
    );
  }

  chooser.addEventListener("change", () => {
    const route = parseUniverseRoute(windowNode.location.hash);
    windowNode.location.hash = buildUniverseRoute(route.view, chooser.value);
  });
  windowNode.addEventListener("hashchange", renderRoute);

  Promise.resolve().then(() => callFunction(
    client, "projects.list", { fields: ["id", "slug", "name"] },
  ))
    .then((callResult) => {
      if (!mounted) return;
      const result = (callResult.envelope && callResult.envelope.result) || {};
      projects = result.rows || [];
      chooser.replaceChildren();
      chooser.disabled = projects.length === 0;
      for (const project of projects) {
        const option = el(
          documentNode, "option", null,
          project.name || project.slug || String(project.id),
        );
        option.value = String(project.id);
        chooser.appendChild(option);
      }
      renderRoute();
    })
    .catch(() => {
      if (!mounted) return;
      projects = [];
      chooser.disabled = true;
      renderRoute();
    });

  return createUnmountHandle(UNIVERSE_APP_CONTRACT_VERSION, () => {
    mounted = false;
    windowNode.removeEventListener("hashchange", renderRoute);
    detachMountedSlots(rootNode, mountedSlotNodes);
    rootNode.replaceChildren();
    detachRootClass();
  });
}
