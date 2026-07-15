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
import {
  buildUniverseRoute,
  createScopePicker,
  knownProjectId,
  NAV,
  navEntry,
  parseUniverseRoute,
  renderStubView,
  SCOPE_NONE,
  scopeForEntry,
  universeNavScope,
} from "./universe_navigation.js";

export {
  UNIVERSE_APP_CONTRACT_VERSION,
  createHttpFunctionClient,
} from "./contract.js";
export { buildUniverseRoute, parseUniverseRoute, universeNavScope };

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
// `rowHref`, when given, makes the first cell of each row the link that opens
// that row's drill-in — a real href, so it can be opened in a new tab.
function renderTable(body, rows, columns, emptyText, rowHref) {
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
    for (const [index, column] of columns.entries()) {
      const text = String(column.value(row) ?? "");
      const cell = el(documentNode, "td", null, rowHref && index === 0 ? undefined : text);
      if (rowHref && index === 0) {
        const link = el(documentNode, "a", "row-link", text);
        link.href = rowHref(row);
        cell.appendChild(link);
      }
      tr.appendChild(cell);
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

// `blocked` arrives as the string "0"/"1", which makes both values truthy —
// read it as a number, never as a bare condition.
function isBlocked(row) {
  return Number(row.blocked) === 1;
}

function renderItemsView(context, main, projectId) {
  const panel = section(context.document, "Items");
  main.replaceChildren(panel);
  loadSection(
    context, panel,
    "items.list.run",
    {
      // The function serves a far wider allowlist than the three fields this
      // table began with; every name here returns today.
      fields: [
        "id", "title", "type", "status", "priority", "blocked", "blocked_reason",
      ],
      project: String(projectId),
    },
    (body, callResult) => {
      const rows = (callResult.envelope.result || {}).rows || [];
      renderTable(body, rows, [
        { label: "id", value: (row) => row.id },
        // Type rides beside status because a status word means nothing without
        // it: each workflow type owns its own status set, and the same word in
        // two types is two different states.
        { label: "type", value: (row) => row.type },
        { label: "title", value: (row) => row.title },
        { label: "status", value: (row) => row.status },
        { label: "priority", value: (row) => row.priority },
        {
          label: "blocked",
          // A bare "yes" states the fact and withholds the answer; the reason
          // is the only part anyone can act on.
          value: (row) => (
            isBlocked(row) ? (row.blocked_reason || "blocked") : ""
          ),
        },
      ], "no items yet",
      (row) => buildUniverseRoute("items", String(projectId), String(row.id)));
    },
  );
}

function renderEventsView(context, main, projectId) {
  const panel = section(context.document, "Events");
  main.replaceChildren(panel);
  loadSection(
    context, panel,
    "events.query.run",
    { project: String(projectId) },
    (body, callResult) => {
      const rows = (callResult.envelope.result || {}).rows || [];
      renderTable(body, rows, [
        { label: "when", value: (row) => row.created_at },
        { label: "event", value: (row) => row.event_name },
        { label: "kind", value: (row) => row.event_kind },
        { label: "severity", value: (row) => row.severity },
        // Whoever the event names: a human actor when there is one, otherwise
        // the service that emitted it.
        { label: "source", value: (row) => row.actor_id || row.service },
      ], "no events yet");
    },
  );
}

// The registry of projects. Every row is already in hand from the roster the
// nav pickers read, so this view re-renders rather than re-fetches.
function renderProjectsView(context, main) {
  const panel = section(context.document, "Projects");
  main.replaceChildren(panel);
  panel.renderEnvelope(
    { status: 200, envelope: { success: true, result: { rows: context.projects() } } },
    (body) => {
      renderTable(body, context.projects(), [
        { label: "id", value: (row) => row.id },
        { label: "name", value: (row) => row.name },
        { label: "slug", value: (row) => row.slug },
      ], "no projects yet");
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

// One item, whichever workflow type it is. `body` is a virtual field the
// engine renders on demand from the item's structured fields, so the detail
// view asks for it rather than reassembling it here.
function renderItemDetailView(context, main, projectId, itemRef) {
  const documentNode = context.document;
  const panel = section(documentNode, `Item ${itemRef}`);
  main.replaceChildren(panel);
  loadSection(
    context, panel,
    "items.get.run",
    {},
    (body, callResult) => {
      const fields = (callResult.envelope.result || {}).fields || {};
      const summary = el(documentNode, "table", "items");
      // A detail view is one row read downward; the same label/value pairs the
      // table shows across, so type still travels with status.
      for (const [label, value] of [
        ["type", fields.type], ["status", fields.status],
        ["priority", fields.priority], ["flow", fields.flow],
        ["project", fields.project], ["created", fields.created_at],
      ]) {
        const tr = el(documentNode, "tr");
        tr.appendChild(el(documentNode, "th", null, label));
        tr.appendChild(el(documentNode, "td", null, String(value ?? "")));
        summary.appendChild(tr);
      }
      body.appendChild(summary);

      const rendered = String(fields.body || "").trim();
      const bodyBlock = el(
        documentNode, rendered ? "pre" : "p", rendered ? "item-body" : "empty",
        rendered || "no body yet",
      );
      body.appendChild(bodyBlock);

      // An epic's tasks are its own decomposition, so they belong on the epic
      // rather than on a screen of their own.
      if (fields.type === "epic") {
        const tasks = section(documentNode, "Tasks");
        main.appendChild(tasks);
        loadSection(
          context, tasks,
          "epic_tasks.list.run",
          { epic: Number(fields.id) },
          (taskBody, taskResult) => {
            const rows = (taskResult.envelope.result || {}).tasks || [];
            renderTable(taskBody, rows, [
              { label: "#", value: (row) => row.task_num },
              { label: "title", value: (row) => row.title },
              { label: "status", value: (row) => row.status },
            ], "no tasks yet");
          },
        );
      }
    },
    { kind: "item", item_ref: String(itemRef), project_id: String(projectId) },
  );
}

// A drill-in belongs to the view whose row opened it; the view stays active in
// the nav and the breadcrumb is the way back.
const DETAIL_RENDERERS = {
  items: renderItemDetailView,
};

// A destination is live exactly when it has a renderer here; every other NAV
// entry renders its `summary` under Coming soon.
const VIEW_RENDERERS = {
  items: renderItemsView,
  strategy: renderStrategyView,
  events: renderEventsView,
  projects: renderProjectsView,
};

// The way back out of a drill-in, naming the view it belongs to. It carries
// the view's project so returning lands on the same rows the row came from.
function createBreadcrumb(documentNode, entry, project, detail) {
  const bar = el(documentNode, "div", "breadcrumb");
  const back = el(documentNode, "a", "breadcrumb-parent", entry.label);
  back.href = buildUniverseRoute(entry.id, project);
  bar.appendChild(back);
  bar.appendChild(el(documentNode, "span", "breadcrumb-sep", "/"));
  bar.appendChild(el(documentNode, "span", "breadcrumb-here", String(detail)));
  return bar;
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
  let projects = [];
  const context = {
    client,
    document: documentNode,
    isMounted: () => mounted,
    // The roster the scope pickers already hold, so a view that only lists
    // projects costs no second call.
    projects: () => projects,
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

  // Each visited scoped view remembers its own project.
  const scopeSelections = new Map();

  function renderRoute() {
    const route = parseUniverseRoute(windowNode.location.hash);
    const entry = navEntry(route.view);
    const project = scopeForEntry(
      entry, route.project, projects, scopeSelections,
    );

    for (const navItem of NAV) {
      const link = navLinks.get(navItem.id);
      link.href = buildUniverseRoute(
        navItem.id,
        navItem.scope === SCOPE_NONE
          ? null
          : (knownProjectId(
            projects, scopeSelections.get(navItem.id),
          ) || project),
      );
      link.classList.toggle("active", navItem.id === entry.id);
    }

    const detailRenderer = route.detail ? DETAIL_RENDERERS[entry.id] : null;
    const renderer = VIEW_RENDERERS[entry.id];
    if (!renderer) {
      renderStubView(context, main, entry);
      return;
    }
    if (entry.scope === SCOPE_NONE) {
      renderer(context, main, null);
      return;
    }
    if (project === null) {
      main.replaceChildren(emptyUniversePanel(documentNode));
      return;
    }
    if (detailRenderer) {
      // A drill-in swaps the view's picker for a breadcrumb: re-scoping a
      // single row to another project is nonsense, and the way out is back.
      const detailHost = el(documentNode, "div", "view-host");
      main.replaceChildren(
        createBreadcrumb(documentNode, entry, project, route.detail),
        detailHost,
      );
      detailRenderer(context, detailHost, project, route.detail);
      return;
    }
    // The picker is the view's own chrome, so it sits in the content column
    // above a host the view owns outright and re-renders into at will.
    const viewHost = el(documentNode, "div", "view-host");
    main.replaceChildren(createScopePicker({
      documentNode, entry, project, projects, renderRoute, scopeSelections,
      windowNode,
    }), viewHost);
    renderer(context, viewHost, project);
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
