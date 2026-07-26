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

// `blocked` arrives as the string "0"/"1", which makes both values truthy —
// read it as a number, never as a bare condition.
function isBlocked(row) {
  return Number(row.blocked) === 1;
}

export function renderItemsView(context, main, scope) {
  const panel = section(context.document, "Items");
  main.replaceChildren(panel);
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, false);
  const idBySlug = new Map(
    projects.map((row) => [String(row.slug), String(row.id)]),
  );
  const fields = [
    "id", "title", "workflow_id", "workflow_version_id", "status",
    "priority", "blocked", "blocked_reason", "project",
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
        { label: "workflow", value: (row) => row.workflow_id },
        { label: "version", value: (row) => row.workflow_version_id },
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

// One item, whichever workflow it uses. `body` is a virtual field the
// engine renders on demand from the item's structured fields.
export function renderItemDetailView(context, main, projectId, itemRef) {
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
        ["workflow", fields.workflow_id],
        ["workflow version", fields.workflow_version_id],
        ["status", fields.status],
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
      if (fields.workflow_id === "epic") {
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
