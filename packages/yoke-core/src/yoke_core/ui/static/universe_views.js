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
// response envelope(s) the section rendered from — a lone envelope for a
// single read, the array of them when a scope fanned out into several.
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

  wrap.renderEnvelopes = (callResults, renderBody) => {
    const envelopes = callResults.map((callResult) => callResult.envelope);
    raw.textContent = JSON.stringify(
      envelopes.length === 1 ? envelopes[0] : envelopes, null, 2,
    );
    body.replaceChildren();
    renderBody(body, callResults);
  };
  wrap.renderEnvelope = (callResult, renderBody) => {
    wrap.renderEnvelopes(
      [callResult],
      (bodyNode, callResults) => renderBody(bodyNode, callResults[0]),
    );
  };
  return wrap;
}

// Semantic color family per state value. Status vocabularies belong to
// workflow types, so this map is a coloring hint and never a gate: any value
// it has not seen renders as a neutral idle pill rather than breaking.
const STATE_PILL_FAMILIES = {
  implementing: "run",
  "reviewing-implementation": "run",
  "reviewed-implementation": "run",
  "polishing-implementation": "run",
  release: "run",
  new: "run",
  executing: "run",
  implemented: "good",
  done: "good",
  active: "good",
  succeeded: "good",
  blocked: "crit",
  failed: "crit",
  error: "crit",
  critical: "crit",
  unclear: "warn",
  warn: "warn",
  warning: "warn",
  stale: "warn",
  // Dependency gate points: an activation gate stops work from starting,
  // an integration gate only orders the landing, a closure gate merely
  // holds the closeout milestone.
  activation: "crit",
  integration: "warn",
  closure: "idle",
};

// A state value rendered as a tinted lozenge with a leading dot, colored by
// its semantic family. Empty values render nothing at all.
function statePill(documentNode, value) {
  const text = String(value ?? "");
  if (!text) return null;
  const family = STATE_PILL_FAMILIES[text.toLowerCase()] || "idle";
  const pill = el(documentNode, "span", `pill ${family}`, text);
  pill.setAttribute("data-state", text);
  return pill;
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
// A column with its own `href` accessor links that cell the same way (for
// views whose linking cell is not the first). A column marked `pill: true`
// renders its value as a state pill; `code: true` renders it as a `code`
// element — deliberately copyable text, never a button.
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
      const cell = el(documentNode, "td");
      if (rowHref && index === 0) {
        const link = el(documentNode, "a", "row-link", text);
        link.href = rowHref(row);
        cell.appendChild(link);
      } else if (column.href) {
        const link = el(documentNode, "a", "row-link", text);
        link.href = column.href(row);
        cell.appendChild(link);
      } else if (column.pill) {
        const pill = statePill(documentNode, text);
        if (pill) cell.appendChild(pill);
      } else if (column.code) {
        if (text) cell.appendChild(el(documentNode, "code", null, text));
      } else {
        cell.textContent = text;
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

// A multi view's scope resolves into per-call project buckets. "all" is one
// unfiltered call (bucket null) when the read serves the whole universe, or
// one call per roster project when the read refuses without one; a project
// set is always one call per member.
function scopeBuckets(scope, projects, requiresProject) {
  if (scope !== "all") return scope;
  return requiresProject ? projects.map((row) => String(row.id)) : [null];
}

// One call per bucket, settled together. A failed bucket fails the whole
// read — silently dropping one would render a partial universe as if it
// were the whole one.
async function settledScopedCalls(context, calls) {
  const callResults = await Promise.all(calls.map(async (call) => {
    try {
      return await callFunction(
        context.client, call.functionId, call.payload, call.target,
      );
    } catch (fetchError) {
      // Network-level failure (server gone, connection refused): status 0
      // marks "no HTTP response" so the panel shows the failure instead
      // of sticking at "loading…".
      return {
        status: 0,
        envelope: { success: false, error: { message: String(fetchError) } },
      };
    }
  }));
  const failed = callResults.find(
    (callResult) => !(callResult.status === 200 && callResult.envelope.success),
  );
  return { callResults, failed };
}

// One fan-out serving several panels: each panel shows the same envelopes
// behind its raw-JSON toggle, and a failed bucket fails them all — the
// panels are facets of one read, so none can honestly render rows while
// another shows the failure.
async function loadScopedPanels(context, panelRenderers, calls) {
  const { callResults, failed } = await settledScopedCalls(context, calls);
  if (!context.isMounted()) return;
  for (const [panel, renderRows] of panelRenderers) {
    panel.renderEnvelopes(
      callResults,
      failed ? (body) => renderError(body, failed) : renderRows,
    );
  }
}

async function loadScopedSection(context, panel, calls, renderRows) {
  return loadScopedPanels(context, [[panel, renderRows]], calls);
}

// Bucket results merged in call order.
function mergedRows(callResults, extract) {
  return callResults.flatMap(
    (callResult) => extract(callResult.envelope.result || {}) || [],
  );
}

// A table scoped to exactly one project needs no project column; "all" and
// multi-member sets label every row with the project it belongs to. The
// column sits beside the leading identifier so a row link stays the first
// cell.
function withProjectColumn(columns, scope, valueOf) {
  if (Array.isArray(scope) && scope.length === 1) return columns;
  return [
    columns[0],
    { label: "project", value: valueOf },
    ...columns.slice(1),
  ];
}

// `blocked` arrives as the string "0"/"1", which makes both values truthy —
// read it as a number, never as a bare condition.
function isBlocked(row) {
  return Number(row.blocked) === 1;
}

function renderItemsView(context, main, scope) {
  const panel = section(context.document, "Items");
  main.replaceChildren(panel);
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, false);
  const idBySlug = new Map(
    projects.map((row) => [String(row.slug), String(row.id)]),
  );
  const fields = [
    "id", "title", "type", "status", "priority", "blocked",
    "blocked_reason", "project",
  ];
  // A row's drill-in carries the row's own project: at exactly one project
  // the scope id is that project; otherwise the roster maps the served slug
  // back to the id the route speaks.
  const rowProject = (row) => (
    (Array.isArray(scope) && scope.length === 1)
      ? scope[0]
      : (idBySlug.get(String(row.project)) || String(row.project))
  );
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "items.list.run",
      payload: bucket === null ? { fields } : { fields, project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      renderTable(body, rows, withProjectColumn([
        { label: "id", value: (row) => row.id },
        { label: "type", value: (row) => row.type },
        { label: "title", value: (row) => row.title },
        { label: "status", value: (row) => row.status, pill: true },
        { label: "priority", value: (row) => row.priority },
        {
          label: "blocked",
          value: (row) => (
            isBlocked(row) ? (row.blocked_reason || "blocked") : ""
          ),
        },
      ], scope, (row) => row.project), "no items yet",
      (row) => buildUniverseRoute("items", rowProject(row), String(row.id)));
    },
  );
}

function renderEventsView(context, main, scope) {
  const panel = section(context.document, "Events");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "events.query.run",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      // Each event row carries the slug of the project it was recorded
      // against — a universe-level event carries none and shows none.
      renderTable(body, rows, withProjectColumn([
        { label: "when", value: (row) => row.created_at },
        { label: "event", value: (row) => row.event_name },
        { label: "kind", value: (row) => row.event_kind },
        { label: "severity", value: (row) => row.severity, pill: true },
        { label: "source", value: (row) => row.actor_id || row.service },
      ], scope, (row) => row.project), "no events yet");
    },
  );
}

// What the system noticed about itself, and what came of it. `reviewed_at` is
// the second half of that sentence: an observation nobody has looked at yet is
// not the same as one that has been through curation, and a row that hid the
// difference would make the loop look closed when it is still open.
function renderOuroborosView(context, main, scope) {
  const panel = section(context.document, "Ouroboros");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "ouroboros.entry.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.entries);
      // Each entry carries the slug of the project it observed — a
      // universe-level observation carries none and shows none.
      renderTable(body, rows, withProjectColumn([
        { label: "when", value: (row) => row.timestamp },
        { label: "category", value: (row) => row.category, pill: true },
        { label: "agent", value: (row) => row.agent },
        { label: "context", value: (row) => row.context },
        {
          label: "reviewed",
          value: (row) => (row.reviewed_at ? row.reviewed_at : ""),
        },
      ], scope, (row) => row.project), "nothing noticed yet");
    },
  );
}

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

function renderStrategyView(context, main, scope) {
  const panel = section(context.document, "Strategy");
  main.replaceChildren(panel);
  const projects = context.projects();
  // The strategy read refuses without a project, so "all" fans out into one
  // call per roster project rather than one unfiltered call.
  const buckets = scopeBuckets(scope, projects, true);
  const slugById = new Map(
    projects.map((row) => [String(row.id), row.slug || String(row.id)]),
  );
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "strategy.doc.list",
      payload: {},
      // Strategy docs are project-scoped through the target, not the payload.
      target: { kind: "global", project_id: String(bucket) },
    })),
    (body, callResults) => {
      // The read carries no per-row project, so each row wears the label of
      // the bucket that requested it — never a guess.
      const docs = callResults.flatMap((callResult, index) => (
        ((callResult.envelope.result || {}).docs || []).map((doc) => ({
          ...doc, project: slugById.get(buckets[index]) || buckets[index],
        }))
      ));
      renderTable(body, docs, withProjectColumn([
        { label: "slug", value: (doc) => doc.slug },
        { label: "title", value: (doc) => doc.title },
        {
          label: "status", pill: true,
          value: (doc) => (doc.archived ? "archived" : "active"),
        },
      ], scope, (doc) => doc.project), "no strategy docs yet");
    },
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
      // The summary is a key/value grid, not a row list — the kv class
      // swaps the column-header table dress for label/value cell rules.
      const summary = el(documentNode, "table", "items kv");
      for (const [label, value] of [
        ["type", fields.type], ["status", fields.status],
        ["priority", fields.priority], ["flow", fields.flow],
        ["project", fields.project], ["created", fields.created_at],
      ]) {
        const tr = el(documentNode, "tr");
        tr.appendChild(el(documentNode, "th", null, label));
        const cell = el(documentNode, "td");
        const pill = label === "status"
          ? statePill(documentNode, value) : null;
        if (pill) cell.appendChild(pill);
        else cell.textContent = String(value ?? "");
        tr.appendChild(cell);
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
              { label: "status", value: (row) => row.status, pill: true },
            ], "no tasks yet");
          },
        );
      }
    },
    { kind: "item", item_ref: String(itemRef), project_id: String(projectId) },
  );
}

// The session, not the item: who runs (the actor, honestly labelled by the
// engine so a system actor never reads as a person), what it holds (its
// active work-claims, rendered server-side from the typed targets), how
// alive it is (engine-derived liveness — the executor-aware TTL numbers
// live in the engine, never here), and what Yoke directed it to do (the
// stored execution lane and mode).
function renderSessionsView(context, main, scope) {
  const panel = section(context.document, "Sessions");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "sessions.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      // Each session row carries the slug of the project it works in.
      renderTable(body, rows, withProjectColumn([
        { label: "session", value: (row) => row.session_id },
        {
          label: "actor",
          value: (row) => {
            const label = row.actor_label ||
              (row.actor_id == null ? "" : `actor ${row.actor_id}`);
            return row.actor_kind === "system" ? `${label} · system` : label;
          },
        },
        { label: "liveness", value: (row) => row.liveness, pill: true },
        { label: "lane", value: (row) => row.execution_lane },
        { label: "mode", value: (row) => row.mode },
        {
          label: "holds",
          value: (row) => (row.claims || [])
            .map((claim) => claim.target).join(", "),
        },
        { label: "item", value: (row) => row.current_item },
        { label: "last activity", value: (row) => row.activity_at },
      ], scope, (row) => row.project), "no sessions yet");
    },
  );
}

// What runs next and why, and what a waiting item waits on. One read serves
// both panels: the engine's ranked ready steps — rank is the engine's own,
// never a display index — and one blocked row per unsatisfied dependency
// edge across every gate point (activation stops a start, integration only
// orders the landing, closure holds the closeout), plus the non-edge waits
// (operator blocks) whose gate cell is honestly empty. There is no progress
// column: no per-item done/total exists in the engine, so none is invented
// here. Frontier rows point at items — the item cell links to the items
// drill-in rather than making the row a frontier drill-in of its own.
function renderFrontierView(context, main, scope) {
  const documentNode = context.document;
  const readyPanel = section(documentNode, "Ready");
  const blockedPanel = section(documentNode, "Blocked");
  main.replaceChildren(readyPanel, blockedPanel);
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, false);
  const idBySlug = new Map(
    projects.map((row) => [String(row.slug), String(row.id)]),
  );
  // A row's item link carries the row's own project: at exactly one project
  // the scope id is that project; otherwise the roster maps the served slug
  // back to the id the route speaks.
  const rowProject = (row) => (
    (Array.isArray(scope) && scope.length === 1)
      ? scope[0]
      : (idBySlug.get(String(row.project)) || String(row.project))
  );
  // The items drill-in speaks bare numeric refs; frontier rows carry YOK-N.
  const itemHref = (row) => buildUniverseRoute(
    "items", rowProject(row), String(row.item_id).replace(/^YOK-/, ""),
  );
  // Exactly one project needs no project column; the column keeps its
  // declared position (beside type), so the shared leading-cell insertion
  // helper does not apply here.
  const scopedColumns = (columns) => (
    (Array.isArray(scope) && scope.length === 1)
      ? columns.filter((column) => column.label !== "project")
      : columns
  );
  loadScopedPanels(context, [
    [readyPanel, (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.ready_rows);
      renderTable(body, rows, scopedColumns([
        { label: "rank", value: (row) => row.rank },
        { label: "item", value: (row) => row.item_id, href: itemHref },
        { label: "type", value: (row) => row.item_type },
        { label: "project", value: (row) => row.project },
        { label: "status", value: (row) => row.status, pill: true },
        { label: "priority", value: (row) => row.priority },
        { label: "next step", value: (row) => row.next_step },
        { label: "run command", value: (row) => row.run_command, code: true },
        { label: "why ready", value: (row) => row.why_ready },
      ]), "nothing ready to run");
    }],
    [blockedPanel, (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.blocked_rows);
      renderTable(body, rows, scopedColumns([
        { label: "item", value: (row) => row.item_id },
        { label: "project", value: (row) => row.project },
        { label: "waiting on", value: (row) => row.blocking_item, code: true },
        { label: "gate", value: (row) => row.gate_point, pill: true },
        { label: "why", value: (row) => row.why },
      ]), "nothing waiting");
    }],
  ], buckets.map((bucket) => ({
    functionId: "frontier.list",
    payload: bucket === null ? {} : { project: bucket },
  })));
}

// Each run of a flow against a target environment. The engine owns the run's
// vocabulary: status colors through the pill hint (a run halted for approval
// keeps status "executing" and so stays a running pill, never a failed one),
// and the stage shows as the text the engine recorded — the stage roster
// belongs to the flow definition, so nothing here hardcodes its shape.
function renderDeliveryRunsView(context, main, scope) {
  const panel = section(context.document, "Runs");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "deployment_runs.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      // The engine lists oldest-first; a runs screen answers "what just
      // happened", so presentation flips to newest-first.
      const rows = mergedRows(callResults, (result) => result.rows)
        .slice().reverse();
      // Each run row carries the slug of the project whose flow ran.
      renderTable(body, rows, withProjectColumn([
        { label: "run", value: (row) => row.id },
        { label: "flow", value: (row) => row.flow },
        { label: "target", value: (row) => row.target_env },
        { label: "stage", value: (row) => row.current_stage },
        { label: "status", value: (row) => row.status, pill: true },
        { label: "created", value: (row) => row.created_at },
      ], scope, (row) => row.project), "no runs yet");
    },
  );
}

// Drill-ins remain children of the view whose row opened them.
export const DETAIL_RENDERERS = { items: renderItemDetailView };

// Tab renderers, keyed view id → tab id. A tab is live exactly when it has a
// renderer here; a declared tab without one renders the honest stub. A view
// appears here only when its NAV entry declares tabs — the same second route
// segment cannot also be a drill-in.
export const TAB_RENDERERS = {
  delivery: { runs: renderDeliveryRunsView },
};

// A destination is live exactly when it has a renderer here.
export const VIEW_RENDERERS = {
  frontier: renderFrontierView,
  items: renderItemsView,
  strategy: renderStrategyView,
  sessions: renderSessionsView,
  events: renderEventsView,
  ouroboros: renderOuroborosView,
  projects: renderProjectsView,
};
