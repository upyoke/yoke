// Read-only workbench view renderers. The app shell owns mounting and routing;
// this module owns function-backed panels and their row/detail presentation.
// The presentation primitives (sections, tables, pills, scoped loaders) live
// in universe_view_support.js.

import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  loadScopedSection,
  loadSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  statePill,
  withProjectColumn,
} from "./universe_view_support.js";
import { renderWorkflowsView } from "./universe_views_workflows.js";

export { section } from "./universe_view_support.js";

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
  items: renderItemsView,
  strategy: renderStrategyView,
  sessions: renderSessionsView,
  events: renderEventsView,
  ouroboros: renderOuroborosView,
  projects: renderProjectsView,
  workflows: renderWorkflowsView,
};
