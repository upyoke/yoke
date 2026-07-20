// Read-only function-backed workbench views; the app shell owns routing and
// universe_view_support.js owns presentation primitives.

import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  loadScopedPanels,
  loadScopedSection,
  loadSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  statePill,
  whoColumn,
  withProjectColumn,
} from "./universe_view_support.js";
import { renderGithubView } from "./universe_views_github.js";
import { renderOrganizationView } from "./universe_views_organization.js";
import { renderOverviewView } from "./universe_views_overview.js";
import { renderPacksView } from "./universe_views_packs.js";
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
      // The served `count` is each bucket's authoritative total, summed
      // across a fan-out. Never rows.length: when the two disagree, the
      // engine's number is the fact.
      const servedCounts = callResults.map(
        (callResult) => (callResult.envelope.result || {}).count,
      );
      panel.setCount(
        servedCounts.every((count) => typeof count === "number")
          ? servedCounts.reduce((total, count) => total + count, 0)
          : null,
      );
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
  // The events read is project-scoped and refuses a call that names no
  // project, so "all" fans out into one call per roster project rather than
  // one unfiltered call.
  const buckets = scopeBuckets(scope, context.projects(), true);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "events.query.run",
      payload: { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      // The fan-out returns one block per project; the pulse is one stream,
      // so the merged rows re-sort newest-first across all buckets.
      const at = (row) => Date.parse(row.created_at) || 0;
      rows.sort((a, b) => at(b) - at(a));
      // No header count here: only a served total or a known-complete set
      // earns one, and this read attests neither.
      // Each event row carries the slug of the project it was recorded
      // against — a universe-level event carries none and shows none.
      renderTable(body, rows, withProjectColumn([
        { label: "when", value: (row) => row.created_at },
        { label: "event", value: (row) => row.event_name },
        { label: "kind", value: (row) => row.event_kind },
        { label: "severity", value: (row) => row.severity, pill: true },
        {
          label: "source",
          // A bare integer reads as data noise; say what the number is.
          value: (row) => (
            row.actor_id !== null && row.actor_id !== undefined
              ? `actor ${row.actor_id}` : (row.service || "")
          ),
        },
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
  // The entry read is project-scoped and refuses a call that names no
  // project, so "all" fans out into one call per roster project rather than
  // one unfiltered call.
  const buckets = scopeBuckets(scope, context.projects(), true);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "ouroboros.entry.list",
      payload: { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.entries);
      // The count is the bounded receipt set fetched for this scope.
      panel.setCount(rows.length);
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
      // the bucket that requested it — never a guess. The bucket id also
      // rides along so a row link can name its project in the route.
      const docs = callResults.flatMap((callResult, index) => (
        ((callResult.envelope.result || {}).docs || []).map((doc) => ({
          ...doc,
          project: slugById.get(buckets[index]) || buckets[index],
          project_id: buckets[index],
        }))
      ));
      // Every bucket served its complete corpus, so the merged length is
      // the fetched total.
      panel.setCount(docs.length);
      renderTable(body, docs, withProjectColumn([
        { label: "slug", value: (doc) => doc.slug },
        { label: "title", value: (doc) => doc.title },
        // The engine resolves the last editor to a label when it knows
        // one; an unattributed doc shows nothing, never a placeholder.
        { label: "owner", value: (doc) => doc.updated_by },
        { label: "last write", value: (doc) => doc.updated_at },
        // Raw bytes exactly as served — the number is the engine's.
        { label: "size", value: (doc) => doc.bytes },
        {
          label: "status", pill: true,
          value: (doc) => (doc.archived ? "archived" : "active"),
        },
      ], scope, (doc) => doc.project), "no strategy docs yet",
      (doc) => buildUniverseRoute("strategy", doc.project_id, doc.slug));
    },
  );
}

// One strategy doc, body included — the drill-in the corpus table opens.
// The doc content is the plan itself, so it renders the same way an item
// body does: served text, monospace, no client-side rewriting.
function renderStrategyDocDetailView(context, main, projectId, slug) {
  const documentNode = context.document;
  const panel = section(documentNode, slug);
  main.replaceChildren(panel);
  loadSection(
    context, panel,
    "strategy.doc.get",
    { slug: String(slug) },
    (body, callResult) => {
      const doc = callResult.envelope.result || {};
      const summary = el(documentNode, "table", "items kv");
      for (const [label, value] of [
        ["project", doc.project_slug],
        ["last write", doc.updated_at],
        ["status", doc.archived_at ? "archived" : "active"],
      ]) {
        const tr = el(documentNode, "tr");
        tr.appendChild(el(documentNode, "th", null, label));
        tr.appendChild(el(documentNode, "td", null, String(value ?? "")));
        summary.appendChild(tr);
      }
      body.appendChild(summary);
      const content = String(doc.content || "").trim();
      body.appendChild(el(
        documentNode, content ? "pre" : "p",
        content ? "item-body" : "empty",
        content || "no content yet",
      ));
    },
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
          {},
          (taskBody, taskResult) => {
            const rows = (taskResult.envelope.result || {}).tasks || [];
            renderTable(taskBody, rows, [
              { label: "#", value: (row) => row.task_num },
              { label: "title", value: (row) => row.title },
              { label: "status", value: (row) => row.status, pill: true },
            ], "no tasks yet");
          },
          // The read resolves the epic through the target, not the payload.
          {
            kind: "epic_task",
            epic_id: Number(fields.id),
            project_id: String(projectId),
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
  // Who runs a session is the actor by default; a host that names accounts
  // (a hosted org) turns the same column into the member it maps to.
  const who = whoColumn(context.capabilities);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "sessions.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      // Every bucket served its complete set, so the merged length is the
      // fetched total.
      panel.setCount(rows.length);
      // Each session row carries the slug of the project it works in.
      renderTable(body, rows, withProjectColumn([
        { label: "session", value: (row) => row.session_id },
        { label: who.label, value: who.value },
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
        {
          label: "rank",
          // Ordinal display of the engine's own zero-based rank — "1" is
          // the engine's top pick, not a display index (raw JSON keeps
          // the served number).
          value: (row) => (
            typeof row.rank === "number" ? row.rank + 1 : row.rank
          ),
        },
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
      // The engine bounds run history and returns the newest receipts first.
      const rows = mergedRows(callResults, (result) => result.rows);
      // Every bucket served its complete set, so the merged length is the
      // fetched total.
      panel.setCount(rows.length);
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

// The pipeline definitions runs execute. The same read that serves the
// lifecycle definition (`workflows.definition.get`) also serves the declared
// deployment flows, and a flow belongs to exactly one project — so this facet
// takes the Delivery scope and fans out the way every other multi view does,
// rather than borrowing the lifecycle screen's universe-wide shape.
function renderDeliveryFlowsView(context, main, scope) {
  const panel = section(context.document, "Flows");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "workflows.definition.get",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.flows);
      // Every bucket served its complete set, so the merged length is the
      // fetched total.
      panel.setCount(rows.length);
      // Each flow row carries the slug of the project that declares it.
      renderTable(body, rows, withProjectColumn([
        { label: "flow", value: (row) => row.id, mono: true },
        { label: "name", value: (row) => row.name },
        { label: "target env", value: (row) => row.target_env },
        { label: "status", value: (row) => row.status, pill: true },
        {
          label: "stages",
          value: (row) => (row.stage_names || []).join(" → "),
        },
        { label: "on failure", value: (row) => row.on_failure },
      ], scope, (row) => row.project), "no deployment flows declared");
    },
  );
}

// The stat-tile row above a report: one number that matters per tile. A
// count the journal could not preserve renders as an em dash, never a
// made-up zero.
function statRow(documentNode, stats) {
  const row = el(documentNode, "div", "stat-row");
  for (const [label, value] of stats) {
    const tile = el(documentNode, "div", "stat");
    tile.appendChild(el(
      documentNode, "div", "n",
      value === null || value === undefined ? "—" : String(value),
    ));
    tile.appendChild(el(documentNode, "div", "l", label));
    row.appendChild(tile);
  }
  return row;
}

// One doctor report body: fact line, stat tiles, then the checks table.
// The three degraded states render honestly — never ran (with the command
// to run, as copyable text), truncated in the journal, or a plain report.
function renderDoctorReport(body, result) {
  const documentNode = body.ownerDocument;
  if (result.never_run) {
    body.appendChild(el(
      documentNode, "p", "empty", "doctor has not run yet",
    ));
    const hint = el(documentNode, "p", "fact-line", "run it with ");
    hint.appendChild(el(
      documentNode, "code", null, "yoke doctor run --quick",
    ));
    body.appendChild(hint);
    return;
  }
  const facts = [`last run ${result.ran_at}`];
  if (result.scope) facts.push(`scope ${result.scope}`);
  body.appendChild(el(documentNode, "p", "fact-line", facts.join(" · ")));
  body.appendChild(statRow(documentNode, [
    ["total", result.total],
    ["passing", result.pass_count],
    ["warnings", result.warn_count],
    ["failing", result.fail_count],
  ]));
  if (result.truncated) {
    body.appendChild(el(
      documentNode, "p", "empty",
      "detail truncated in the journal; run doctor again for a fresh report",
    ));
    return;
  }
  renderTable(body, result.results || [], [
    { label: "check", value: (row) => row.hc, mono: true },
    { label: "name", value: (row) => row.name },
    { label: "result", value: (row) => row.severity, pill: true },
  ], "no checks recorded");
}

// The last completed doctor run — doctor findings persist nowhere but the
// events journal, so this reads the journal, not a table of runs. "all"
// serves the newest run regardless of project in one call; a project set
// asks per member and labels each report with the project it answers for.
function renderDoctorView(context, main, scope) {
  const panel = section(context.document, "Doctor");
  main.replaceChildren(panel);
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, false);
  const nameById = new Map(projects.map(
    (row) => [String(row.id), row.name || row.slug || String(row.id)],
  ));
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "doctor.last_run.get",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      callResults.forEach((callResult, index) => {
        if (buckets.length > 1) {
          body.appendChild(el(
            body.ownerDocument, "h3", "report-heading",
            nameById.get(buckets[index]) || String(buckets[index]),
          ));
        }
        renderDoctorReport(body, callResult.envelope.result || {});
      });
    },
  );
}

// What Yoke can reach on a project's behalf, and how honestly it can claim
// so. The engine owns the vocabulary end to end: the capability column shows
// the STORED type string (never an invented label), kind/state arrive
// derived, and the verified stamp is whichever source the engine trusts for
// that type (the GitHub row wears its repo-binding freshness). A NULL stamp
// renders as the word "never" — configured-but-never-verified is a warning,
// not a resting state.
function renderCapabilitiesView(context, main, scope) {
  const panel = section(context.document, "Capabilities");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "projects.capabilities.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      // Each capability row carries the slug of the project declaring it.
      renderTable(body, rows, withProjectColumn([
        { label: "capability", value: (row) => row.type, mono: true },
        { label: "kind", value: (row) => row.kind, pill: true },
        { label: "settings", value: (row) => row.settings_summary || "—" },
        { label: "verified", value: (row) => row.verified_at || "never" },
        { label: "state", value: (row) => row.state, pill: true },
      ], scope, (row) => row.project), "no capabilities declared yet");
    },
  );
}

// Drill-ins remain children of the view whose row opened them.
export const DETAIL_RENDERERS = {
  items: renderItemDetailView,
  strategy: renderStrategyDocDetailView,
};

// Tab renderers, keyed view id → tab id. A tab is live exactly when it has a
// renderer here; a declared tab without one renders the honest stub. A view
// appears here only when its NAV entry declares tabs — the same second route
// segment cannot also be a drill-in.
export const TAB_RENDERERS = {
  delivery: { runs: renderDeliveryRunsView, flows: renderDeliveryFlowsView },
};

// A destination is live exactly when it has a renderer here.
export const VIEW_RENDERERS = {
  overview: renderOverviewView,
  frontier: renderFrontierView,
  items: renderItemsView,
  strategy: renderStrategyView,
  sessions: renderSessionsView,
  capabilities: renderCapabilitiesView,
  events: renderEventsView,
  doctor: renderDoctorView,
  ouroboros: renderOuroborosView,
  projects: renderProjectsView,
  packs: renderPacksView,
  workflows: renderWorkflowsView,
  github: renderGithubView,
  organization: renderOrganizationView,
};
