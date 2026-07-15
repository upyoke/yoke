// Read-only workbench view renderers. The app shell owns mounting and routing;
// this module owns function-backed panels and their row/detail presentation.

import { buildUniverseRoute } from "./universe_navigation.js";

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
export function section(documentNode, title) {
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

  wrap.renderEnvelope = (callResult, renderBody) => {
    raw.textContent = JSON.stringify(callResult.envelope, null, 2);
    body.replaceChildren();
    renderBody(body, callResult);
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
      const cell = el(
        documentNode, "td", null,
        rowHref && index === 0 ? undefined : text,
      );
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
      fields: [
        "id", "title", "type", "status", "priority", "blocked",
        "blocked_reason",
      ],
      project: String(projectId),
    },
    (body, callResult) => {
      const rows = (callResult.envelope.result || {}).rows || [];
      renderTable(body, rows, [
        { label: "id", value: (row) => row.id },
        { label: "type", value: (row) => row.type },
        { label: "title", value: (row) => row.title },
        { label: "status", value: (row) => row.status },
        { label: "priority", value: (row) => row.priority },
        {
          label: "blocked",
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
        { label: "source", value: (row) => row.actor_id || row.service },
      ], "no events yet");
    },
  );
}

// The registry of projects is already in hand from the roster nav pickers use.
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
// engine renders on demand from the item's structured fields.
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
      body.appendChild(el(
        documentNode, rendered ? "pre" : "p", rendered ? "item-body" : "empty",
        rendered || "no body yet",
      ));

      // An epic's tasks are its own decomposition, so they live on the epic.
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

// Drill-ins remain children of the view whose row opened them.
export const DETAIL_RENDERERS = { items: renderItemDetailView };

// A destination is live exactly when it has a renderer here.
export const VIEW_RENDERERS = {
  items: renderItemsView,
  strategy: renderStrategyView,
  events: renderEventsView,
  projects: renderProjectsView,
};
